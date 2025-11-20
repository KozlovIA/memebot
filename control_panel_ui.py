# app.py
"""
Flask мем-панель для ручной модерации
Без потери качества изображений, без создания .thumb_ файлов
Требуется: Flask==2.3.2
Запуск: python app.py
"""
import os
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_from_directory, abort, Response
from werkzeug.utils import secure_filename
import base64
from source.mongo_manager import MongoManager

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

mongo = MongoManager()
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
<title>🤡Панель модерации мемов</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
  body { padding: 1rem; background:#fdfdfd; }
  .top-row { align-items: center; }
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
    transition: transform 0.15s ease;
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
  @media (max-width: 768px) {
    .grid { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 480px) {
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
    <div class="d-flex justify-content-between align-items-center mb-3 top-row">
      <div>
        <h3 class="mb-0">🤡Панель модерации мемов</h3>
        <div class="text-muted fs-5">Всего мемов: <span id="count">0</span></div>
      </div>
      <div>
        <button id="refresh" class="btn btn-outline-primary me-2">Обновить</button>
        <label class="btn btn-success mb-0">
        <span id="uploadText">Добавить фото</span>
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

async function updateCount() {
  try {
    const r = await fetch('/api/count');
    if (!r.ok) return;
    const data = await r.json();
    document.getElementById('count').innerText = data.count;
  } catch (e) {
    console.error('count error', e);
  }
}

async function loadPage(p) {
  const r = await fetch(`/api/images?page=${p}`);
  if (!r.ok) return;
  const data = await r.json();
  data.images.forEach(id => {
    const div = document.createElement('div');
    div.className = 'thumb';
    // store id on dataset for later removal
    div.dataset.memeId = id;
    div.innerHTML = `<img src="/memes/${id}" alt="Мем #${id}">`;
    div.onclick = (e) => {
      // prevent click when clicking inside delete or other controls in future
      if (e.target.tagName.toLowerCase() === 'button') return;
      openModal(id);
    };
    gallery.appendChild(div);
  });
  if (!data.has_more) loadMore.style.display = 'none';
  await updateCount();
}

function openModal(name) {
  currentFile = name;
  document.getElementById('fileName').innerText = `Мем #${name}`;
  document.getElementById('fullImage').src = '/memes/' + name;
  const modal = new bootstrap.Modal(document.getElementById('modalView'));
  modal.show();
}

// helper: remove thumb element with animation
function removeThumbAnimated(memeId) {
  const el = Array.from(gallery.children).find(d => d.dataset && d.dataset.memeId == String(memeId));
  if (!el) return;
  // fix current height, then animate to zero
  const height = el.getBoundingClientRect().height;
  el.style.transition = 'height 200ms ease, opacity 200ms ease, margin 200ms ease';
  el.style.height = height + 'px';
  // force reflow
  void el.offsetHeight;
  el.style.opacity = '0';
  el.style.height = '0px';
  el.style.margin = '0px';
  setTimeout(() => {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }, 220);
}

document.getElementById('deleteBtn').onclick = async () => {
  if (currentFile === null) return;
  if (!confirm(`Удалить "Мем #${currentFile}"?`)) return;

  const r = await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({filename: currentFile})
  });

  if (r.ok) {
    // Скрываем модалку
    const modalEl = document.getElementById('modalView');
    const modalInstance = bootstrap.Modal.getInstance(modalEl);
    modalInstance.hide();

    // Плавно удаляем соответствующую миниатюру без полной перезагрузки
    removeThumbAnimated(currentFile);

    // Обновляем счётчик
    updateCount();

    // Сбрасываем currentFile
    currentFile = null;
  } else if (r.status === 404) {
    alert('Мем не найден (уже удалён). Обновляю галерею.');
    // На случай рассинхронизации — перезагрузим ленту
    gallery.innerHTML = ''; page = 1; loadMore.style.display = 'block'; loadPage(1);
    updateCount();
  } else {
    alert('Ошибка удаления');
  }
};

loadMore.onclick = () => { page++; loadPage(page); };
document.getElementById('refresh').onclick = () => {
  gallery.innerHTML = ''; page = 1; loadMore.style.display = 'block'; loadPage(1); updateCount();
};

document.getElementById('upload').onchange = async (e) => {
  const files = e.target.files;
  if (!files.length) return;

  const fd = new FormData();
  for (const f of files) fd.append('files', f);

  const input = document.getElementById('upload');
  const text = document.getElementById('uploadText');

  input.disabled = true;
  text.textContent = 'Загрузка...';

  const r = await fetch('/api/upload', {method:'POST', body:fd});

  input.disabled = false;
  text.textContent = 'Добавить фото';

  e.target.value = '';

  if (r.ok) {
    gallery.innerHTML = '';
    page = 1;
    loadMore.style.display = 'block';
    loadPage(1);
    updateCount();
  } else {
    alert('Ошибка загрузки');
  }
};


// initial load
loadPage(1);
updateCount();
</script>
</body>
</html>
"""


# ------------------ Маршруты ------------------
@app.route("/")
def index():
    return render_template_string(HTML, cols=IMAGES_PER_ROW, per_page=THUMBNAILS_PER_PAGE)


@app.route("/memes/<int:meme_id>")
def serve_image(meme_id):
    meme = mongo.get_meme_by_id(meme_id)
    if not meme or "image" not in meme:
        abort(404)
    img_data = base64.b64decode(meme["image"])
    # Попытка минимально корректно вернуть тип, хотя в коде раньше было png
    return Response(img_data, mimetype="image/png")


@app.route("/api/images")
def api_images():
    page = int(request.args.get("page", 1))
    per_page = THUMBNAILS_PER_PAGE

    all_memes = mongo.get_all_memes()
    start = (page - 1) * per_page
    end = start + per_page

    memes_page = all_memes[start:end]
    meme_ids = [m["_id"] for m in memes_page]

    return jsonify({
        "images": meme_ids,
        "has_more": end < len(all_memes)
    })


@app.route("/api/count")
def api_count():
    try:
        c = mongo.count_memes()
    except Exception:
        c = 0
    return jsonify({"count": c})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if not files:
        return "Нет файлов", 400
    saved_ids = []
    for f in files:
        name = secure_filename(f.filename)
        if not allowed_file(name):
            return f"Недопустимое расширение: {name}", 400
        base64_str = base64.b64encode(f.read()).decode("utf-8")
        meme_id = mongo.add_meme_base64(base64_str)
        saved_ids.append(meme_id)
    return jsonify({"saved": saved_ids})


@app.route("/api/delete", methods=["POST"])
def api_delete():
    data = request.get_json()
    if not data or "filename" not in data:
        return "Неверный запрос", 400
    try:
        meme_id = int(data["filename"])
    except Exception:
        return "Неверный id", 400
    if mongo.delete_meme(meme_id):
        return "", 204
    else:
        return "Не найден", 404


if __name__ == "__main__":
    # На Windows watchdog/reloader иногда вызывает OSError 10038 (select на не-сокете).
    # Чтобы избежать этой ошибки в разработке — выключаем use_reloader.
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=DEBUG, use_reloader=False)
