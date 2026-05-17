class CodeMindError(Exception):
    """所有自定义异常的基类。"""


class IndexingError(CodeMindError):
    """索引过程中的错误（单文件失败不应中断整个索引）。"""


class ParserError(IndexingError):
    """Tree-sitter 解析失败。"""


class RetrievalError(CodeMindError):
    """检索失败（应被 tool 层捕获并返回结构化错误给 LLM）。"""


class StorageError(CodeMindError):
    """持久化层错误。"""


class ConfigError(CodeMindError):
    """配置错误（必须在启动时尽早抛出，不允许延迟暴露）。"""
