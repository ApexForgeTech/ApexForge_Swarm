import os
import pandas as pd
from typing import Optional
from .base import BaseTool

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None


class ReadDocTool(BaseTool):
    name = "read_document"
    description = (
        "Read the content of a PDF, DOCX, CSV, or Excel file. "
        "Useful for extracting information from documents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "The path to the file to read."},
            "max_chars": {"type": "integer", "description": "Max characters to return. Default: 10000."},
        },
        "required": ["file_path"],
    }

    def execute(self, file_path: str, max_chars: int = 10000) -> str:
        if not os.path.exists(file_path):
            return f"Error: File '{file_path}' not found."

        ext = os.path.splitext(file_path)[1].lower()
        try:
            content = ""
            if ext == ".pdf":
                if not PdfReader:
                    return "Error: pypdf library not installed."
                reader = PdfReader(file_path)
                for page in reader.pages:
                    content += page.extract_text() + "\n"
            
            elif ext == ".docx":
                if not Document:
                    return "Error: python-docx library not installed."
                doc = Document(file_path)
                content = "\n".join([p.text for p in doc.paragraphs])
            
            elif ext == ".csv":
                df = pd.read_csv(file_path)
                content = df.to_string(index=False)
            
            elif ext in [".xlsx", ".xls"]:
                df = pd.read_excel(file_path)
                content = df.to_string(index=False)
            
            else:
                return f"Error: Unsupported file extension '{ext}'. Use standard file tools for text files."

            if not content.strip():
                return "The document is empty or no text could be extracted."

            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"
            
            return content

        except Exception as e:
            return f"Error reading document: {e}"
