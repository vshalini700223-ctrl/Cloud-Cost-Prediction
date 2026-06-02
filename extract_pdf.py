from pypdf import PdfReader

pdf_path = r"O:\saad uni\Cloud Computing\Project\BCS223205.pdf"
output_path = "proposal_text.txt"

reader = PdfReader(pdf_path)

with open(output_path, "w", encoding="utf-8") as file:
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        file.write(f"\n\n--- Page {page_number} ---\n\n")
        file.write(text)

print(f"Extracted text saved to {output_path}")