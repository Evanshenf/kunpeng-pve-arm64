# mypy: ignore-errors
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
"""310P workaround for the AICPU IndexPut crash (error 507018).

This is the implementation proposed by vllm-ascend PR #12914. It replaces
boolean-mask ``index_put_`` with integer-index ``index_copy_`` on 310P only.
"""

import torch
import vllm.model_executor.models.utils as model_utils
from vllm.model_executor.models.utils import (
    _embedding_count_expression,
    _flatten_embeddings,
)


def _merge_multimodal_embeddings_310p(
    inputs_embeds: torch.Tensor,
    multimodal_embeddings,
    is_multimodal: torch.Tensor,
) -> torch.Tensor:
    """Merge multimodal embeddings without the broken 310P IndexPut path."""
    if len(multimodal_embeddings) == 0:
        return inputs_embeds

    mm_embeds_flat = _flatten_embeddings(multimodal_embeddings)
    input_dtype = inputs_embeds.dtype

    try:
        mm_idx = torch.nonzero(is_multimodal, as_tuple=True)[0].to(
            device=inputs_embeds.device,
            non_blocking=True,
        )
        inputs_embeds.index_copy_(
            0,
            mm_idx,
            mm_embeds_flat.to(
                device=inputs_embeds.device,
                dtype=input_dtype,
            ),
        )
    except RuntimeError as exc:
        num_actual_tokens = len(mm_embeds_flat)
        num_expected_tokens = is_multimodal.sum().item()

        if num_actual_tokens != num_expected_tokens:
            expression = _embedding_count_expression(multimodal_embeddings)
            raise ValueError(
                f"Attempted to assign {expression} = {num_actual_tokens} "
                f"multimodal tokens to {num_expected_tokens} placeholders"
            ) from exc

        raise ValueError("Error during index copy operation") from exc

    return inputs_embeds


model_utils._merge_multimodal_embeddings = _merge_multimodal_embeddings_310p
