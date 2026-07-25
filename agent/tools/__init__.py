"""工具基类"""
from pydantic import BaseModel

class ToolInfo(BaseModel):
    name: str; description: str; enabled: bool = True; version: str = "1.0"

class BaseTool:
    name: str = ""; description: str = ""; version: str = "1.0"
    def __init__(self):
        if not self.name: self.name = self.__class__.__name__
    def validate_input(self, **kwargs) -> list[str]: return []
    def execute(self, **kwargs) -> dict: raise NotImplementedError
    def to_info(self) -> ToolInfo:
        return ToolInfo(name=self.name, description=self.description, version=self.version)
    def __repr__(self): return f"<Tool {self.name}: {self.description}>"
