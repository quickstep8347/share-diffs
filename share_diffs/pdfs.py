try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    raise ImportError(
        "pypdf needs to be installed, consider installing this package with all dependencies or at least the pdf-group"
    )
from typing import List
from pathlib import Path


def split_bytes_into_n(
    data: bytes,
    n: int,
) -> List[bytes]:
    """
    Split `data` into n parts with lengths as equal as possible.
    If `copy=False`, returns memoryviews (zero-copy). Otherwise returns bytes.
    Example: len(data)=10, n=3  -> lengths [4, 3, 3]
    """
    if n < 1:
        raise ValueError("n must be >= 1")

    L = len(data)
    q, r = divmod(L, n)  # r chunks get one extra byte
    sizes = [q + 1] * r + [q] * (n - r)  # e.g., [4,3,3]

    out = []
    idx = 0
    for s in sizes:
        out.append(data[idx : idx + s])  # copies
        idx += s
    return out


def attach_to_pdfs(pdf_input_folder: str, pdf_output_folder: str, data: bytes):
    """splits the data into n parts where n is the number of pdf files in pdf_input_folder and (over-)writes those to output_folder."""
    input_path = Path(pdf_input_folder)
    input_pdfs = list(input_path.glob("*.pdf"))
    patches = split_bytes_into_n(data, len(input_pdfs))
    for i, (pdf_path, patch) in enumerate(zip(input_pdfs, patches)):
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.add_attachment(f"file_{i}.bin", patch)
        Path(pdf_output_folder).mkdir(parents=True, exist_ok=True)
        writer.write(Path(pdf_output_folder) / pdf_path.name)


def recover_from_pdfs(pdf_folder: str) -> bytes:
    pdfs = list(Path(pdf_folder).glob("*.pdf"))
    payloads = {}
    for pdf in pdfs:
        reader = PdfReader(pdf)
        name, data = list(reader.attachments.items())[0]
        payloads[name] = data[0]

    # join binary payloads according to sorted names
    sorted_payloads = sorted(payloads.items(), key=lambda x: x[0])
    joined_payload = sorted_payloads[0][1]
    for _, payload in sorted_payloads[1:]:
        joined_payload += payload
    return joined_payload
