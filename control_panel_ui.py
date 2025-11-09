# app.py
"""
Flask мем-панель для ручной модерации
Без потери качества изображений, без создания .thumb_ файлов
Требуется: Flask==2.3.2
Запуск: python app.py
"""
import os
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_from_directory, abort
from werkzeug.utils import secure_filename

# ------------------ НАСТРОЙКИ ------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 8501
DEBUG = True

MEMES_FOLDER = Path("memes")
MEMES_FOLDER.mkdir(exist_ok=True)

IMAGES_PER_ROW = 8
ROWS_ON_SCREEN = 10
THUMBNAILS_PER_PAGE = IMAGES_PER_ROW * ROWS_ON_SCREEN

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SORT_BY_MTIME_DESC = True
# ------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # до 50 МБ на загрузку


# ------------------ Утилиты ------------------
def allowed_file(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXT


def list_images_sorted():
    """Список файлов из папки, отсортированный по дате"""
    files = []
    for p in MEMES_FOLDER.iterdir():
        if p.is_file() and allowed_file(p.name) and not p.name.startswith(".thumb_"):
            files.append((p.name, p.stat().st_mtime))
    files.sort(key=lambda x: x[1], reverse=SORT_BY_MTIME_DESC)
    return [f for f, _ in files]


# ------------------ HTML шаблон ------------------
HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>💅🏻Панель модерации мемов</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body { padding: 1rem; background:#fdfdfd; }
  .grid {
    display: grid;
    grid-template-columns: repeat({{ cols }}, 1fr);
    gap: 0.5rem;
  }
  .thumb {
    cursor: pointer;
    overflow: hidden;
    border-radius: 0.5rem;
    background-color: #eee;
    aspect-ratio: 1/1;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.2s ease;
  }
  .thumb img:hover {
    transform: scale(1.05);
  }
  @memes (max-width: 768px) {
    .grid { grid-template-columns: repeat(2, 1fr); }
  }
  @memes (max-width: 480px) {
    .grid { grid-template-columns: repeat(1, 1fr); }
  }
  .full-img {
    width: 100%;
    height: auto;
    max-height: 80vh;
    object-fit: contain;
  }
</style>
</head>
<body>
  <div class="container-fluid">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h3>💅🏻Панель модерации мемов</h3>
      <div>
        <button id="refresh" class="btn btn-outline-primary me-2">Обновить</button>
        <label class="btn btn-success mb-0">
          Добавить фото
          <input id="upload" type="file" accept="image/*" multiple hidden>
        </label>
      </div>
    </div>

    <div id="gallery" class="grid"></div>

    <div class="d-flex justify-content-center mt-3">
      <button id="loadMore" class="btn btn-secondary">Загрузить ещё</button>
    </div>
  </div>

  <!-- Просмотр -->
  <div class="modal fade" id="modalView" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog modal-dialog-centered modal-fullscreen-sm-down modal-xl">
      <div class="modal-content">
        <div class="modal-header">
          <h5 id="fileName" class="modal-title"></h5>
          <button class="btn-close" data-bs-dismiss="modal"></button>
        </div>
        <div class="modal-body text-center">
          <img id="fullImage" class="full-img" src="" alt="">
        </div>
        <div class="modal-footer">
          <button id="deleteBtn" class="btn btn-danger">Удалить</button>
          <button class="btn btn-secondary" data-bs-dismiss="modal">Закрыть</button>
        </div>
      </div>
    </div>
  </div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
let page = 1;
let perPage = {{ per_page }};
let gallery = document.getElementById('gallery');
let loadMore = document.getElementById('loadMore');
let currentFile = null;

async function loadPage(p) {
  const r = await fetch(`/api/images?page=${p}`);
  if (!r.ok) return;
  const data = await r.json();
  data.images.forEach(name => {
    const div = document.createElement('div');
    div.className = 'thumb';
    div.innerHTML = `<img src="/memes/${encodeURIComponent(name)}" alt="${name}">`;
    div.onclick = () => openModal(name);
    gallery.appendChild(div);
  });
  if (!data.has_more) loadMore.style.display = 'none';
}

function openModal(name) {
  currentFile = name;
  document.getElementById('fileName').innerText = name;
  document.getElementById('fullImage').src = '/memes/' + encodeURIComponent(name);
  const modal = new bootstrap.Modal(document.getElementById('modalView'));
  modal.show();
}

document.getElementById('deleteBtn').onclick = async () => {
  if (!currentFile) return;
  if (!confirm(`Удалить "${currentFile}"?`)) return;
  const r = await fetch('/api/delete', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({filename: currentFile})
  });
  if (r.ok) {
    [...gallery.children].forEach(div => {
      const img = div.querySelector('img');
      if (img && img.alt === currentFile) div.remove();
    });
    bootstrap.Modal.getInstance(document.getElementById('modalView')).hide();
  } else alert('Ошибка удаления');
};

loadMore.onclick = () => { page++; loadPage(page); };
document.getElementById('refresh').onclick = () => {
  gallery.innerHTML = ''; page = 1; loadMore.style.display = 'block'; loadPage(1);
};

document.getElementById('upload').onchange = async (e) => {
  const files = e.target.files;
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const btn = document.querySelector('label.btn-success');
  btn.classList.add('disabled');
  btn.innerText = 'Загрузка...';
  const r = await fetch('/api/upload', {method:'POST', body:fd});
  btn.classList.remove('disabled');
  btn.innerText = 'Добавить фото';
  if (r.ok) {
    gallery.innerHTML = ''; page = 1; loadMore.style.display = 'block'; loadPage(1);
  } else alert('Ошибка загрузки');
};

loadPage(1);
</script>
</body>
</html>
"""


# ------------------ Маршруты ------------------
@app.route("/")
def index():
    return render_template_string(HTML, cols=IMAGES_PER_ROW, per_page=THUMBNAILS_PER_PAGE)


@app.route("/memes/<path:filename>")
def serve_image(filename):
    safe = Path(filename).name
    path = MEMES_FOLDER / safe
    if not path.exists():
        abort(404)
    return send_from_directory(MEMES_FOLDER, safe)


@app.route("/api/images")
def api_images():
    page = int(request.args.get("page", 1))
    imgs = list_images_sorted()
    start = (page - 1) * THUMBNAILS_PER_PAGE
    end = start + THUMBNAILS_PER_PAGE
    return jsonify({
        "images": imgs[start:end],
        "has_more": end < len(imgs)
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if not files:
        return "Нет файлов", 400
    saved = []
    for f in files:
        name = secure_filename(f.filename)
        if not allowed_file(name):
            return f"Недопустимое расширение: {name}", 400
        path = MEMES_FOLDER / name
        if path.exists():
            base, ext = os.path.splitext(name)
            i = 1
            while (MEMES_FOLDER / f"{base}_{i}{ext}").exists():
                i += 1
            name = f"{base}_{i}{ext}"
            path = MEMES_FOLDER / name
        f.save(path)
        saved.append(name)
    return jsonify({"saved": saved})


@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json()
    if not data or "filename" not in data:
        return "Неверный запрос", 400
    name = Path(data["filename"]).name
    path = MEMES_FOLDER / name
    if not path.exists():
        return "Не найден", 404
    path.unlink()
    return "", 204


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=DEBUG)
