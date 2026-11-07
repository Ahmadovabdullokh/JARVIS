
from app.tools.common import optional_import, resolve_path


def _docx():
    return optional_import("docx")


def _openpyxl():
    return optional_import("openpyxl")


def _pptx():
    return optional_import("pptx")


def _pypdf():
    return optional_import("pypdf")


def register(registry):

    @registry.tool(
        "docx_create",
        "Создать документ Word с заголовком и текстом.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "title": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["path", "text"],
        },
        category="office",
    )
    def docx_create(path, title=None, text=""):
        docx = _docx()
        if docx is None:
            return "Для работы с Word установите python-docx."
        document = docx.Document()
        if title:
            document.add_heading(str(title), level=1)
        for line in str(text).split("\n"):
            document.add_paragraph(line)
        output = resolve_path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output))
        return f"Документ создан: {output}"

    @registry.tool(
        "docx_read",
        "Прочитать текст документа Word.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="office",
    )
    def docx_read(path, limit=12000):
        docx = _docx()
        if docx is None:
            return "Для работы с Word установите python-docx."
        document = docx.Document(str(resolve_path(path, must_exist=True)))
        lines = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(lines)[: int(limit or 12000)] or "(документ пуст)"

    @registry.tool(
        "docx_append",
        "Дописать текст в документ Word.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["path", "text"],
        },
        category="office",
    )
    def docx_append(path, text):
        docx = _docx()
        if docx is None:
            return "Для работы с Word установите python-docx."
        target = resolve_path(path, must_exist=True)
        document = docx.Document(str(target))
        for line in str(text).split("\n"):
            document.add_paragraph(line)
        document.save(str(target))
        return f"Текст добавлен в {target}"

    @registry.tool(
        "docx_replace",
        "Заменить текст в документе Word.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
        category="office",
    )
    def docx_replace(path, old, new):
        docx = _docx()
        if docx is None:
            return "Для работы с Word установите python-docx."
        target = resolve_path(path, must_exist=True)
        document = docx.Document(str(target))
        count = 0
        for paragraph in document.paragraphs:
            if old in paragraph.text:
                paragraph.text = paragraph.text.replace(str(old), str(new))
                count += 1
        document.save(str(target))
        return f"Заменено абзацев: {count}."

    @registry.tool(
        "xlsx_create",
        "Создать Excel-таблицу из строк.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "rows": {"type": "array"},
                "sheet": {"type": "string"},
            },
            "required": ["path", "rows"],
        },
        category="office",
    )
    def xlsx_create(path, rows, sheet="Sheet1"):
        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = str(sheet or "Sheet1")
        for row in rows or []:
            worksheet.append(list(row) if isinstance(row, (list, tuple)) else [row])
        output = resolve_path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(str(output))
        return f"Таблица создана: {output}"

    @registry.tool(
        "xlsx_read",
        "Прочитать Excel-таблицу.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "sheet": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="office",
    )
    def xlsx_read(path, sheet=None, limit=200):
        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        workbook = openpyxl.load_workbook(
            str(resolve_path(path, must_exist=True)),
            data_only=True,
        )
        worksheet = workbook[sheet] if sheet else workbook.active
        lines = []
        for row in worksheet.iter_rows(values_only=True):
            lines.append(" | ".join("" if value is None else str(value) for value in row))
            if len(lines) >= int(limit or 200):
                break
        return "\n".join(lines) or "(лист пуст)"

    @registry.tool(
        "xlsx_sheets",
        "Список листов Excel-файла.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="office",
    )
    def xlsx_sheets(path):
        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        workbook = openpyxl.load_workbook(
            str(resolve_path(path, must_exist=True)),
            read_only=True,
        )
        return "\n".join(workbook.sheetnames)

    @registry.tool(
        "xlsx_write_cell",
        "Записать значение в ячейку Excel.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "cell": {"type": "string"},
                "value": {},
                "sheet": {"type": "string"},
            },
            "required": ["path", "cell", "value"],
        },
        category="office",
    )
    def xlsx_write_cell(path, cell, value, sheet=None):
        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        target = resolve_path(path, must_exist=True)
        workbook = openpyxl.load_workbook(str(target))
        worksheet = workbook[sheet] if sheet else workbook.active
        worksheet[str(cell)] = value
        workbook.save(str(target))
        return f"Ячейка {cell} обновлена."

    @registry.tool(
        "xlsx_append",
        "Дописать строку в Excel-таблицу.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "row": {"type": "array"},
                "sheet": {"type": "string"},
            },
            "required": ["path", "row"],
        },
        category="office",
    )
    def xlsx_append(path, row, sheet=None):
        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        target = resolve_path(path, must_exist=True)
        workbook = openpyxl.load_workbook(str(target))
        worksheet = workbook[sheet] if sheet else workbook.active
        worksheet.append(list(row or []))
        workbook.save(str(target))
        return "Строка добавлена."

    @registry.tool(
        "xlsx_to_csv",
        "Преобразовать лист Excel в CSV.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "sheet": {"type": "string"},
            },
            "required": ["path", "target"],
        },
        category="office",
    )
    def xlsx_to_csv(path, target, sheet=None):
        import csv

        openpyxl = _openpyxl()
        if openpyxl is None:
            return "Для работы с Excel установите openpyxl."
        workbook = openpyxl.load_workbook(
            str(resolve_path(path, must_exist=True)),
            data_only=True,
        )
        worksheet = workbook[sheet] if sheet else workbook.active
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            for row in worksheet.iter_rows(values_only=True):
                writer.writerow(row)
        return f"CSV сохранён: {output}"

    @registry.tool(
        "pptx_create",
        "Создать презентацию PowerPoint.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "title": {"type": "string"},
                "slides": {"type": "array"},
            },
            "required": ["path"],
        },
        category="office",
    )
    def pptx_create(path, title=None, slides=None):
        pptx = _pptx()
        if pptx is None:
            return "Для работы с PowerPoint установите python-pptx."
        presentation = pptx.Presentation()
        if title:
            slide = presentation.slides.add_slide(
                presentation.slide_layouts[0]
            )
            slide.shapes.title.text = str(title)
        for item in slides or []:
            slide = presentation.slides.add_slide(
                presentation.slide_layouts[1]
            )
            if isinstance(item, dict):
                slide.shapes.title.text = str(item.get("title", ""))
                slide.placeholders[1].text = str(item.get("text", ""))
            else:
                slide.shapes.title.text = str(item)
        output = resolve_path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(str(output))
        return f"Презентация создана: {output}"

    @registry.tool(
        "pptx_read",
        "Прочитать текст презентации.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="office",
    )
    def pptx_read(path, limit=12000):
        pptx = _pptx()
        if pptx is None:
            return "Для работы с PowerPoint установите python-pptx."
        presentation = pptx.Presentation(
            str(resolve_path(path, must_exist=True))
        )
        lines = []
        for index, slide in enumerate(presentation.slides, start=1):
            lines.append(f"--- Слайд {index} ---")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    lines.append(shape.text)
        return "\n".join(lines)[: int(limit or 12000)]

    @registry.tool(
        "pdf_read",
        "Извлечь текст из PDF.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pages": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
        category="office",
    )
    def pdf_read(path, pages=None, limit=12000):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        reader = pypdf.PdfReader(str(resolve_path(path, must_exist=True)))
        selected = range(len(reader.pages))
        if pages:
            selected = []
            for part in str(pages).split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    selected.extend(range(int(start) - 1, int(end)))
                elif part:
                    selected.append(int(part) - 1)
        lines = []
        for index in selected:
            if 0 <= index < len(reader.pages):
                lines.append(reader.pages[index].extract_text() or "")
        return "\n".join(lines)[: int(limit or 12000)] or "(текст не найден)"

    @registry.tool(
        "pdf_info",
        "Информация о PDF-файле.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        category="office",
    )
    def pdf_info(path):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        reader = pypdf.PdfReader(str(resolve_path(path, must_exist=True)))
        lines = [f"Страниц: {len(reader.pages)}"]
        if reader.metadata:
            for key, value in reader.metadata.items():
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    @registry.tool(
        "pdf_merge",
        "Объединить несколько PDF в один.",
        {
            "type": "object",
            "properties": {
                "sources": {"type": "array"},
                "target": {"type": "string"},
            },
            "required": ["sources", "target"],
        },
        category="office",
    )
    def pdf_merge(sources, target):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        writer = pypdf.PdfWriter()
        for source in sources or []:
            reader = pypdf.PdfReader(str(resolve_path(source, must_exist=True)))
            for page in reader.pages:
                writer.add_page(page)
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as handle:
            writer.write(handle)
        return f"PDF объединён: {output}"

    @registry.tool(
        "pdf_split",
        "Разделить PDF на страницы.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["path", "output_dir"],
        },
        category="office",
    )
    def pdf_split(path, output_dir):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        source = resolve_path(path, must_exist=True)
        folder = resolve_path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        reader = pypdf.PdfReader(str(source))
        files = []
        for index, page in enumerate(reader.pages, start=1):
            writer = pypdf.PdfWriter()
            writer.add_page(page)
            output = folder / f"{source.stem}_{index}.pdf"
            with open(output, "wb") as handle:
                writer.write(handle)
            files.append(str(output))
        return "Созданы файлы:\n" + "\n".join(files)

    @registry.tool(
        "pdf_create",
        "Создать PDF с текстом.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "text": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["path", "text"],
        },
        category="office",
    )
    def pdf_create(path, text, title=None):
        reportlab = optional_import("reportlab.pdfgen.canvas")
        if reportlab is None:
            return "Для создания PDF установите reportlab."
        output = resolve_path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        canvas = reportlab.Canvas(str(output))
        height = 842
        y = height - 60
        if title:
            canvas.setFont("Helvetica-Bold", 16)
            canvas.drawString(50, y, str(title)[:80])
            y -= 40
        canvas.setFont("Helvetica", 11)
        for line in str(text).split("\n"):
            for chunk in [line[i : i + 90] for i in range(0, len(line), 90)] or [""]:
                if y < 50:
                    canvas.showPage()
                    canvas.setFont("Helvetica", 11)
                    y = height - 60
                canvas.drawString(50, y, chunk)
                y -= 16
        canvas.save()
        return f"PDF создан: {output}"

    @registry.tool(
        "pdf_rotate",
        "Повернуть страницы PDF.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "angle": {"type": "integer"},
            },
            "required": ["path", "target", "angle"],
        },
        category="office",
    )
    def pdf_rotate(path, target, angle=90):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        reader = pypdf.PdfReader(str(resolve_path(path, must_exist=True)))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            page.rotate(int(angle or 90))
            writer.add_page(page)
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as handle:
            writer.write(handle)
        return f"PDF повёрнут: {output}"

    @registry.tool(
        "pdf_encrypt",
        "Зашифровать PDF паролем.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["path", "target", "password"],
        },
        category="office",
        danger="confirm",
    )
    def pdf_encrypt(path, target, password):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        reader = pypdf.PdfReader(str(resolve_path(path, must_exist=True)))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(str(password))
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as handle:
            writer.write(handle)
        return f"PDF зашифрован: {output}"

    @registry.tool(
        "pdf_decrypt",
        "Расшифровать PDF паролем.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["path", "target", "password"],
        },
        category="office",
        danger="confirm",
    )
    def pdf_decrypt(path, target, password):
        pypdf = _pypdf()
        if pypdf is None:
            return "Для работы с PDF установите pypdf."
        reader = pypdf.PdfReader(str(resolve_path(path, must_exist=True)))
        if reader.is_encrypted:
            reader.decrypt(str(password))
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "wb") as handle:
            writer.write(handle)
        return f"PDF расшифрован: {output}"

    @registry.tool(
        "pdf_images_to_pdf",
        "Собрать PDF из изображений.",
        {
            "type": "object",
            "properties": {
                "images": {"type": "array"},
                "target": {"type": "string"},
            },
            "required": ["images", "target"],
        },
        category="office",
    )
    def pdf_images_to_pdf(images, target):
        PIL = optional_import("PIL.Image")
        if PIL is None:
            return "Для работы с изображениями установите Pillow."
        pages = []
        for item in images or []:
            image = PIL.open(str(resolve_path(item, must_exist=True)))
            if image.mode != "RGB":
                image = image.convert("RGB")
            pages.append(image)
        if not pages:
            return "Не указаны изображения."
        output = resolve_path(target)
        output.parent.mkdir(parents=True, exist_ok=True)
        pages[0].save(
            str(output),
            save_all=True,
            append_images=pages[1:],
        )
        return f"PDF из изображений: {output}"
