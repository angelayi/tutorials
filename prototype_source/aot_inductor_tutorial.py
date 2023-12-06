# -*- coding: utf-8 -*-

"""
AOTInductor Tutorial
==========================
"""

######################################################################
#
# .. warning::
#
#     AOTInductor and its related features are in prototype status and are
#     subject to backwards compatibility breaking changes. It is not meant to be
#     used in any production environment.
#
#
# AOTInductor is a specialized version of
# `TorchInductor <https://dev-discuss.pytorch.org/t/torchinductor-a-pytorch-native-compiler-with-define-by-run-ir-and-symbolic-shapes/747>`__
# which takes an exported PyTorch model, optimizes it, and generates a shared
# library. These compiled artifacts can be deployed to non-Python environments,
# which are commonly used for inference deployments.
#
# AOTInductor is a vital component along the
# `export <https://pytorch.org/docs/main/export.html>`__ path as it provides a way
# to run an exported model without a Python runtime.
#
# In this tutorial, you will learn how take a PyTorch model, export it to a
# compilation graph, pass it to AOTInductor to be compiled into a shared binary,
# and run this binary.
#
# ..note:: a modern NVIDIA GPU (H100, A100, or V100) is recommended for this
# tutorial in order to reproduce the speedup numbers shown below and documented
# elsewhere.

######################################################################
# Entrypoint
# ----------
#
# The entrypoint to AOTInductor is through the ``torch._export.aot_compile``
# function. Note that this function is still in prototype stage and is subject to change.
#
# The signature is:
#
# .. code:: python
#
#   torch._export.aot_compile(
#       module: Callable,
#       args: Tuple[Any, ...],
#       kwargs: Optional[Dict[str, Any]] = None,
#       *,
#       dynamic_shapes: Optional[Dict[str, Any]] = None,
#       options: Optional[Dict[str, Any]] = None,
#   ) -> Tuple[str, bytes]
#
# This function does the following:
#
#    1. Exports the given model into a compilation graph through the
#      `torch.export <https://pytorch.org/docs/main/export.html>`__ workflow. If
#      there are any errors when exporting the model, please refer to the
#      `torch.export <https://pytorch.org/docs/main/export.html>`__ documentation.
#    2. Compiles the exported program using TorchInductor into a shared library.
#    3. Returns the path to the shared library.
#

import torch
import torch._export
import torch.utils._pytree as pytree
from typing import Any, Tuple, Mapping

class M(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.branch1 = torch.nn.Sequential(
            torch.nn.Linear(64, 32), torch.nn.ReLU()
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.branch1(x)

def _normalize_inputs(example_inputs) -> Tuple[Tuple[Any], Mapping[str, Any]]:
    if isinstance(example_inputs, dict):
        return (), example_inputs
    else:
        return example_inputs, {}

with torch.no_grad():
    m = M().to("cuda")
    example_inputs = (torch.randn(32, 64, device="cuda"),)
    example_args, example_kwargs = _normalize_inputs(example_inputs)

    so_path, exported_program = torch._export.aot_compile(
        m, args=example_args, kwargs=example_kwargs
    )

print(".so path:")
print(so_path)
print()
print("Exported graph passed to inductor:")
print(exported_program)
print()

######################################################################
# We can also inspect the generated C++ code associated with the shared library
# through looking at the ``so_path``:

print("Generated C++ Code:")
with open(f"{so_path[:-3]}.cpp", 'r') as f:
    print(f.read())
print()

######################################################################
# Running the .so
# ---------------
#
# To run the ``.so``, we can import ``aot_inductor_launcher`` from
# ``torch._inductor.utils`` which includes some starter C++ code to launch the
# program.
#
# The runnable program takes in a list of flattened arguments, and returns a
# list of flattened outputs, so we will need to do a little bit of preprocessing
# to match the calling/returning convention of the eager module.

from torch._inductor.utils import aot_inductor_launcher

aot_inductor_model_container = torch.utils.cpp_extension.load_inline(
    name="aot_inductor",
    cpp_sources=[aot_inductor_launcher(so_path, "cuda")],
    functions=["run"],
    with_cuda=True,
)

def run_container(example_inputs):
    flat_example_inputs, _ = pytree.tree_flatten(example_inputs)
    flat_outputs = aot_inductor_model_container.run(flat_example_inputs)
    outputs = pytree.tree_unflatten(flat_outputs, exported_program.call_spec.out_spec)
    return outputs

example_inputs = (torch.randn(32, 64, device="cuda"),)
run_container(*example_inputs)
