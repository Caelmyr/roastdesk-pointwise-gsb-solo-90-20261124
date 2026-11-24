"""Connect tray photos, interactive analysis and inspection archives."""

from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from image_lab.validation import Invalid

from . import analysis, demo, frame, model, output
from .store import Library


def install(app, root):
    library = Library(root)
    desk = Blueprint("roast", __name__, url_prefix="/roast")

    def body():
        return model.document(request.get_json(silent=True))

    def inspect(record, data):
        return analysis.inspect(frame.pixels(library, record), model.settings(record, data.get("settings", {})))

    @app.get("/")
    def home():
        return render_template("roastdesk.html")

    @desk.get("/health")
    def health():
        return jsonify(status="ready", service="roastdesk")

    @desk.get("/samples")
    def samples():
        return jsonify(library.list())

    @desk.post("/demo")
    def practice():
        return jsonify(demo.create(library)), 201

    @desk.post("/samples")
    def upload():
        picture = request.files.get("photo")
        if not picture or not picture.filename:
            raise Invalid("Choose a tray photo in PNG or JPEG format.")
        filename = model.text(Path(picture.filename).name)
        image = frame.decode(picture.stream.read(model.MAX_UPLOAD + 1))
        title = model.text(request.form.get("title"), Path(filename).stem)
        return jsonify(library.create(title, image, filename, model.defaults(*image.size))), 201

    @desk.post("/prepared")
    def prepared_sample():
        chosen = body()
        project = model.text(chosen.get("project"))
        result_id = model.text(chosen.get("result"))
        preparation = app.extensions["results"]
        meta = preparation.metadata(project, result_id)
        if meta["stale"]:
            raise Invalid("Run preparation again before sending this result to RoastDesk.")
        path = preparation.image_path(project, "image", result_id)
        image = frame.decode(path.read_bytes())
        record = library.create(model.text(meta.get("name"), "Prepared tray"), image, "prepared-tray.png",
                                model.defaults(*image.size), prepared={"project": project, "result": result_id})
        return jsonify(record), 201

    @desk.get("/samples/<sample_id>")
    def sample(sample_id):
        return jsonify(library.sample(sample_id))

    @desk.get("/samples/<sample_id>/source.png")
    def source(sample_id):
        saved = request.args.get("report")
        record = library.report(sample_id, saved) if saved else library.sample(sample_id)
        return send_file(library.source(record), mimetype="image/png",
                         as_attachment="download" in request.args, download_name="tray-source.png", max_age=0)

    @desk.post("/samples/<sample_id>/inspect")
    def preview(sample_id):
        return jsonify(inspect(library.sample(sample_id), body()))

    @desk.post("/samples/<sample_id>/window")
    def window(sample_id):
        data = body()
        record = library.sample(sample_id)
        settings = model.settings(record, data.get("settings", {}))
        return jsonify(analysis.recommend(frame.pixels(library, record), settings, data.get("size")))

    @desk.put("/samples/<sample_id>/settings")
    def revise(sample_id):
        data = body()
        record = library.sample(sample_id)
        settings = model.settings(record, data.get("settings", {}))
        return jsonify(library.revise(sample_id, data.get("revision"), settings))

    @desk.post("/samples/<sample_id>/point")
    def probe(sample_id):
        data = body()
        saved = data.get("report")
        record = library.report(sample_id, saved) if saved else library.sample(sample_id)
        settings = record["settings"] if saved else model.settings(record, data.get("settings", {}))
        point = model.point(data.get("point"), record["width"], record["height"])
        return jsonify(analysis.locate(frame.pixels(library, record), settings, point))

    @desk.post("/samples/<sample_id>/reports")
    def retain(sample_id):
        data = body()
        result = inspect(library.sample(sample_id), data)
        sample_record, archive = library.retain(sample_id, data.get("revision"), result)
        return jsonify(sample=sample_record, report=archive), 201

    @desk.get("/samples/<sample_id>/reports/<report_id>")
    def report(sample_id, report_id):
        return jsonify(library.report(sample_id, report_id))

    @desk.get("/samples/<sample_id>/reports/<report_id>/beans.csv")
    def csv(sample_id, report_id):
        archive = library.report(sample_id, report_id)
        return Response(output.table(archive), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=beans-{report_id[:8]}.csv"})

    @desk.get("/samples/<sample_id>/reports/<report_id>/overlay.png")
    def marked(sample_id, report_id):
        archive = library.report(sample_id, report_id)
        pixels = output.overlay(library.source(archive), archive)
        return send_file(BytesIO(pixels), mimetype="image/png", as_attachment=True,
                         download_name=f"tray-{report_id[:8]}-marked.png", max_age=0)

    app.register_blueprint(desk)
