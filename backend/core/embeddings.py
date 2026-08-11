import os
import sys
import logging
import asyncio

# Monkey-patch transformers to fix Jina model compatibility under transformers v5.9.0
try:
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    from typing import List, Set, Tuple

    def find_pruneable_heads_and_indices(
        heads: List[int], n_heads: int, head_size: int, already_pruned_heads: Set[int]
    ) -> Tuple[Set[int], torch.LongTensor]:
        """
        Finds the heads and their indices taking already_pruned_heads into account.
        """
        mask = torch.ones(n_heads, head_size)
        heads = set(heads) - already_pruned_heads 
        for head in heads:
            # Compute how many pruned heads are before the head and move the index accordingly
            head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
            mask[head] = 0
        mask = mask.view(-1).contiguous().eq(1)
        index: torch.LongTensor = torch.arange(len(mask))[mask].long()
        return heads, index

    import transformers.pytorch_utils
    transformers.pytorch_utils.find_pruneable_heads_and_indices = find_pruneable_heads_and_indices

    import transformers
    original_getattribute = transformers.PretrainedConfig.__getattribute__
    def patched_getattribute(self, key):
        try:
            return original_getattribute(self, key)
        except AttributeError:
            if key in ("is_decoder", "add_cross_attention"):
                return False
            raise
    transformers.PretrainedConfig.__getattribute__ = patched_getattribute

    # Patch get_head_mask which is missing in transformers v5.x
    def get_head_mask(self, head_mask, num_hidden_layers, is_attention_chunked=False):
        if head_mask is not None:
            if head_mask.dim() == 1:
                head_mask = head_mask.unsqueeze(0).unsqueeze(0).unsqueeze(-1).unsqueeze(-1)
                head_mask = head_mask.expand(num_hidden_layers, -1, -1, -1, -1)
            elif head_mask.dim() == 2:
                head_mask = head_mask.unsqueeze(1).unsqueeze(-1).unsqueeze(-1)
            if is_attention_chunked:
                head_mask = head_mask.unsqueeze(-1)
        else:
            head_mask = [None] * num_hidden_layers
        return head_mask
    transformers.PreTrainedModel.get_head_mask = get_head_mask
except Exception:
    pass

from sentence_transformers import SentenceTransformer
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_text_model_instance = None
_code_model_instance = None
_lock = asyncio.Lock()


def get_model_path(relative_path: str) -> str:
    if os.path.isabs(relative_path):
        return relative_path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(os.path.dirname(current_dir))
    return os.path.abspath(os.path.join(backend_dir, relative_path))


def _apply_dynamic_patches() -> None:
    import sys
    import torch
    for name in list(sys.modules.keys()):
        if "modeling_bert" in name:
            module = sys.modules[name]
            if hasattr(module, "JinaBertEmbeddings") and not hasattr(module.JinaBertEmbeddings, "_patched"):
                orig_forward = module.JinaBertEmbeddings.forward
                def patched_forward(self, input_ids=None, token_type_ids=None, *args, **kwargs):
                    if token_type_ids is not None:
                        token_type_ids = torch.zeros_like(token_type_ids)
                    return orig_forward(self, input_ids=input_ids, token_type_ids=token_type_ids, *args, **kwargs)
                module.JinaBertEmbeddings.forward = patched_forward
                module.JinaBertEmbeddings._patched = True


def get_text_model() -> SentenceTransformer:
    global _text_model_instance
    if _text_model_instance is not None:
        return _text_model_instance

    settings = get_settings()
    model_path = get_model_path(settings.TEXT_EMBEDDING_MODEL_PATH)
    if not os.path.exists(model_path) or not os.listdir(model_path):
        os.makedirs(model_path, exist_ok=True)
        logger.info("Local text model not found at %s. Downloading %s...", model_path, settings.TEXT_EMBEDDING_MODEL_NAME)
        model = SentenceTransformer(settings.TEXT_EMBEDDING_MODEL_NAME, trust_remote_code=True)
        model.save(model_path)
        logger.info("Text model successfully saved to: %s", model_path)
        _text_model_instance = model
    else:
        logger.info("Loading text model from local directory: %s", model_path)
        _text_model_instance = SentenceTransformer(model_path, trust_remote_code=True)

    return _text_model_instance


def get_code_model() -> SentenceTransformer:
    global _code_model_instance
    if _code_model_instance is not None:
        return _code_model_instance

    settings = get_settings()
    model_path = get_model_path(settings.CODE_EMBEDDING_MODEL_PATH)
    if not os.path.exists(model_path) or not os.listdir(model_path):
        os.makedirs(model_path, exist_ok=True)
        logger.info("Local code model not found at %s. Downloading %s...", model_path, settings.CODE_EMBEDDING_MODEL_NAME)
        model = SentenceTransformer(settings.CODE_EMBEDDING_MODEL_NAME, trust_remote_code=True)
        model.save(model_path)
        logger.info("Code model successfully saved to: %s", model_path)
        _code_model_instance = model
    else:
        logger.info("Loading code model from local directory: %s", model_path)
        _code_model_instance = SentenceTransformer(model_path, trust_remote_code=True)

    _code_model_instance.max_seq_length = 512
    _apply_dynamic_patches()
    return _code_model_instance


async def embed_texts(texts: list[str], model_type: str = "text") -> list[list[float]]:
    """
    Generate embeddings for a list of texts asynchronously using either the text or code model.
    """
    import gc

    async with _lock:
        if model_type == "code":
            model = await asyncio.to_thread(get_code_model)
        else:
            model = await asyncio.to_thread(get_text_model)

    def _encode(model, texts):
        import torch
        with torch.no_grad():
            result = model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=min(len(texts), 16),  # limit internal batch to reduce peak memory
            )
        # Force cleanup of temporary tensors
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return result

    embeddings = await asyncio.to_thread(_encode, model, texts)
    if hasattr(embeddings, "tolist"):
        return embeddings.tolist()
    return [list(e) for e in embeddings]


async def embed_query(text: str, model_type: str = "text") -> list[float]:
    """
    Generate embedding for a single query text.
    """
    embeddings = await embed_texts([text], model_type=model_type)
    return embeddings[0]