from itertools import chain
from typing import Iterator, List


class Comments:
    def __init__(self, iter_connections: Iterator[str], parts_expr: List[str]):
        self.iter_connections = iter_connections
        self.parts_expr = parts_expr

    def generate(self) -> Iterator[tuple[str, List[str]]]:
        """Genera cada comentario junto con los usuarios utilizados."""

        last_part = self.parts_expr[-1]

        while True:
            if len(self.parts_expr) == 1:
                yield last_part, []
            else:
                try:
                    users = list(next(self.iter_connections))
                except StopIteration:
                    return

                comment = ''.join(chain.from_iterable(zip(self.parts_expr, users)))
                yield (comment + last_part).replace(r'\@', '@'), users
