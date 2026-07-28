# Copyright 2026 The Drasi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Embed the Drasi continuous-query engine directly in your Python application.

`drasi.Drasi` is async. For scripts and notebooks, `drasi.sync.Drasi` offers the
same API without `await`.
"""

from . import sync, types
from ._drasi import (
    DRASI_CORE_VERSION,
    DRASI_LIB_VERSION,
    DRASI_SDK_VERSION,
    ERROR_CODES,
    ConfigError,
    Drasi,
    DrasiError,
    PluginCompatibilityError,
    PluginError,
    PluginNotFoundError,
    PluginSignatureError,
    SourceError,
    Stream,
    StreamLaggedError,
    UnknownKindError,
    __version__,
    host_info,
)

__all__ = [
    "sync",
    "types",
    "DRASI_CORE_VERSION",
    "DRASI_LIB_VERSION",
    "DRASI_SDK_VERSION",
    "ERROR_CODES",
    "ConfigError",
    "Drasi",
    "DrasiError",
    "PluginCompatibilityError",
    "PluginError",
    "PluginNotFoundError",
    "PluginSignatureError",
    "SourceError",
    "Stream",
    "StreamLaggedError",
    "UnknownKindError",
    "__version__",
    "host_info",
]
