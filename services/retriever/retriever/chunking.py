from __future__ import annotations

from .providers import Chunk, ExtractedDocument, ExtractedSegment


def _tokenize(text: str) -> list[str]:
    return text.split()


def _detokenize(tokens: list[str]) -> str:
    return " ".join(tokens).strip()


class SimpleStructureAwareChunker:
    def chunk(
        self,
        document: ExtractedDocument,
        *,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        ordinal = 0
        for segment in document.segments:
            for block in self._blocks(segment):
                tokens = _tokenize(block)
                if not tokens:
                    continue
                step = max(1, chunk_size_tokens - chunk_overlap_tokens)
                start = 0
                while start < len(tokens):
                    window = tokens[start : start + chunk_size_tokens]
                    if not window:
                        break
                    chunks.append(
                        Chunk(
                            text=_detokenize(window),
                            ordinal=ordinal,
                            source_segment=segment,
                            token_count=len(window),
                        )
                    )
                    ordinal += 1
                    if start + chunk_size_tokens >= len(tokens):
                        break
                    start += step
        return chunks

    @staticmethod
    def _blocks(segment: ExtractedSegment) -> list[str]:
        blocks = [block.strip() for block in segment.text.split("\n\n") if block.strip()]
        return blocks or [segment.text]
