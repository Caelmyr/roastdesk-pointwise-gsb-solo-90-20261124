const $ = id => document.getElementById(id);
const fields = ["threshold", "minimum_area", "target_low", "target_high"];
const overlayColors = {dark: "#859dff", target: "#8de4ae", light: "#ffb358"};
const state = {sample: null, result: null, report: null, photo: null, selected: null,
    probe: null, picking: false, corner: null, showMarks: true, sampling: null};
let busy = false;

async function request(path, method = "GET", body) {
    const options = {method};
    if (body instanceof FormData) options.body = body;
    else if (body !== undefined) {
        options.headers = {"Content-Type": "application/json"};
        options.body = JSON.stringify(body);
    }
    const response = await fetch("/roast" + path, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
}

function samplePath(suffix = "") {
    return "/samples/" + state.sample.id + suffix;
}

function notice(message = "") {
    $("notice").textContent = message;
    $("notice").hidden = !message;
}

function run(action) {
    return async event => {
        event?.preventDefault();
        if (busy) return;
        busy = true;
        notice();
        try {
            await action(event);
        } catch (error) {
            notice(error.message);
        } finally {
            busy = false;
        }
    };
}

function inputs() {
    const base = state.result.settings;
    const values = Object.fromEntries(fields.map(key => [key, $("settings").elements[key].valueAsNumber]));
    values.minimum_retained = $("settings").elements.minimum_retained.valueAsNumber / 100;
    return {...base, ...values, exclude: values.threshold === base.threshold ? base.exclude : []};
}

function displaySettings(settings) {
    for (const key of fields) $("settings").elements[key].value = settings[key];
    $("settings").elements.minimum_retained.value = Math.round(settings.minimum_retained * 100);
    const [left, top, right, bottom] = settings.box;
    $("cropReadout").textContent = "Crop " + (right - left) + " × " + (bottom - top) + " px from " + left + ", " + top;
}

function renderedPosition(event) {
    const canvas = $("canvas");
    const rect = canvas.getBoundingClientRect();
    const scale = Math.min(rect.width / canvas.width, rect.height / canvas.height);
    const insetX = (rect.width - scale * canvas.width) / 2;
    const insetY = (rect.height - scale * canvas.height) / 2;
    const x = Math.floor((event.clientX - rect.left - insetX) / scale);
    const y = Math.floor((event.clientY - rect.top - insetY) / scale);
    if (x >= 0 && x < canvas.width && y >= 0 && y < canvas.height) return [x, y];
    return null;
}

function polygon(ctx, points) {
    if (!points.length) return;
    ctx.beginPath();
    points.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.closePath();
    ctx.stroke();
}

function draw() {
    const canvas = $("canvas");
    const ctx = canvas.getContext("2d");
    ctx.drawImage(state.photo, 0, 0);
    if (state.showMarks) {
        const [left, top, right, bottom] = state.result.settings.box;
        ctx.strokeStyle = "#fffbe7";
        ctx.lineWidth = 2;
        ctx.setLineDash([7, 5]);
        ctx.strokeRect(left + 1, top + 1, Math.max(0, right - left - 2), Math.max(0, bottom - top - 2));
        ctx.setLineDash([]);
        for (const row of state.result.rows) {
            if (row.excluded && !$("showExcluded").checked) continue;
            const active = row.id === state.selected;
            ctx.strokeStyle = active ? "#fffdf8" : row.excluded ? "#ff8281" : overlayColors[row.band];
            ctx.lineWidth = active ? 4 : 2;
            ctx.beginPath();
            row.outline.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
            ctx.closePath();
            ctx.stroke();
            const [x, y] = row.center;
            ctx.font = "600 15px sans-serif";
            ctx.fillStyle = "#39241c";
            ctx.fillRect(x - 4, y - 14, ctx.measureText(row.id).width + 9, 20);
            ctx.fillStyle = ctx.strokeStyle;
            ctx.fillText(row.id, x, y + 1);
            if (row.sampling) {
                ctx.fillStyle = "#f2c14e88";
                for (const points of row.avoided) { ctx.beginPath(); ctx.moveTo(...points[0]); points.slice(1).forEach(p => ctx.lineTo(...p)); ctx.closePath(); ctx.fill(); }
                ctx.strokeStyle = "#3ed6c0";
                ctx.lineWidth = 2;
                row.retained.forEach(points => polygon(ctx, points));
            }
        }
        if (state.sampling) {
            ctx.fillStyle = "#f2c14e66";
            for (const points of state.sampling.outline.avoided) { ctx.beginPath(); ctx.moveTo(...points[0]); points.slice(1).forEach(p => ctx.lineTo(...p)); ctx.closePath(); ctx.fill(); }
            ctx.strokeStyle = "#3ed6c0";
            ctx.lineWidth = 2;
            state.sampling.outline.retained.forEach(points => polygon(ctx, points));
            ctx.strokeStyle = "#f2c14e";
            ctx.lineWidth = 2;
            state.sampling.outline.avoided.forEach(points => polygon(ctx, points));
        }
    }
    const marker = state.corner || state.probe?.point;
    if (marker) {
        const [x, y] = marker;
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x - 8, y);
        ctx.lineTo(x + 8, y);
        ctx.moveTo(x, y - 8);
        ctx.lineTo(x, y + 8);
        ctx.stroke();
    }
}

function tooltip() {
    if (state.picking) return state.corner ? "Choose the opposite corner." : "Choose the first corner of the crop.";
    if (!state.probe) return "Click the tray to inspect a source pixel.";
    const p = state.probe;
    return "(" + p.point.join(", ") + ") · Source RGB " + p.rgb.join(" / ") +
        " · Lightness " + p.lightness + (p.bean ? " · Bean " + p.bean : " · No measured bean");
}

function cell(row, value) {
    const td = row.insertCell();
    td.textContent = value;
    return td;
}

function rowButton(label, action) {
    const button = document.createElement("button");
    button.textContent = label;
    if (action) button.addEventListener("click", run(action));
    return button;
}

function beanTable() {
    const list = $("rows");
    list.replaceChildren();
    const rows = state.result.rows.filter(row => !row.excluded || $("showExcluded").checked);
    if (!rows.length) {
        const empty = cell(list.insertRow(), "No measured beans in the current crop.");
        empty.colSpan = 7;
        return;
    }
    for (const bean of rows) {
        const row = list.insertRow();
        row.dataset.bean = bean.id;
        if (bean.id === state.selected) row.classList.add("active");
        if (bean.excluded) row.classList.add("ignored");
        const label = bean.id + (bean.touches_crop ? " · crop edge" : "");
        cell(row, "").appendChild(rowButton(label, () => selectPoint(bean.seed)));
        cell(row, bean.area);
        const color = cell(row, bean.rgb.join(" / "));
        const swatch = document.createElement("span");
        swatch.className = "swatch";
        swatch.style.background = "rgb(" + bean.rgb.join(", ") + ")";
        color.prepend(swatch);
        cell(row, bean.lightness);
        cell(row, bean.band);
        cell(row, bean.sampled_area ?? bean.area);
        const use = cell(row, "");
        if (state.report) use.textContent = bean.excluded ? "Excluded" : "Included";
        else {
            const b = rowButton(bean.excluded ? "Include" : "Exclude", () => toggleBean(bean.id));
            b.setAttribute("aria-label", (bean.excluded ? "Include " : "Exclude ") + bean.id);
            use.append(b);
        }
    }
}

function renderSummary(summary) {
    $("sampleCount").textContent = summary.count + " included";
    for (const key of ["mean", "median", "spread"]) $(key).textContent = summary[key]?.toFixed(2) ?? "—";
    for (const name of ["dark", "target", "light"]) {
        $(name).textContent = summary.bands[name] + " " + name;
    }
    $("excluded").textContent = summary.excluded + " excluded · " + summary.area.toLocaleString() + " measured px²";
    const max = Math.max(1, ...summary.histogram.map(item => item.count));
    const bars = summary.histogram.map(item => {
        const bar = document.createElement("span");
        bar.style.height = (item.count * 100 / max) + "%";
        bar.title = item.edge + "–" + (item.edge + 15) + ": " + item.count;
        return bar;
    });
    $("histogram").replaceChildren(...bars);
}

function firstOption(title, id = "") {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = title;
    return option;
}

function renderSampling() {
    const suggestion = state.sampling;
    $("sampling").hidden = !suggestion;
    if (!suggestion) return;
    const archived = !!state.report || suggestion.adopted;
    $("samplingBean").textContent = suggestion.bean;
    const retake = suggestion.status !== "ready";
    $("samplingState").textContent = retake ? "Retake photo" : archived ? "Sampling adopted" : "Suggested";
    $("samplingState").className = "badge" + (retake ? " retake" : "");
    const percent = (suggestion.retained_ratio * 100).toFixed(0);
    const minimum = (suggestion.minimum_ratio * 100).toFixed(0);
    const reading = suggestion.lightness === null ? "No usable reading."
        : "With this area: RGB " + suggestion.rgb.join(" / ") + " · lightness " + suggestion.lightness +
          " · " + suggestion.band + " band.";
    const whole = suggestion.whole.lightness === null ? "" :
        " The whole-bean reading was RGB " + suggestion.whole.rgb.join(" / ") +
        " · lightness " + suggestion.whole.lightness + ".";
    $("samplingSummary").textContent = "Keeps " + suggestion.retained_area + " of " +
        suggestion.area + " px (" + percent + "%, minimum " + minimum + "%). " + reading +
        (retake ? " Too little bean face would remain, so the current reading is kept; retake the photo."
                : whole);
    $("adoptSampling").hidden = retake || archived;
    $("restoreSampling").hidden = !suggestion.adopted || !!state.report;
    $("samplingImage").hidden = retake;
    $("samplingImage").href = "/roast" + samplePath("/sampling/" + encodeURIComponent(suggestion.bean) +
        "/overlay.png") + (state.report ? "?report=" + state.report.id : "");
}

function render() {
    draw();
    $("viewerStatus").textContent = tooltip();
    beanTable();
    renderSummary(state.result.summary);
    renderSampling();
    displaySettings(state.result.settings);
    const archived = !!state.report;
    $("inputs").disabled = archived;
    $("crop").disabled = archived;
    $("saveReport").hidden = archived;
    $("live").hidden = !archived;
    $("downloads").hidden = !archived;
    $("reportList").replaceChildren(firstOption("Live tray"), ...state.sample.reports.map(item =>
        firstOption(new Date(item.created).toLocaleString() + " · " + item.count + " beans", item.id)));
    $("reportList").value = state.report?.id || "";
    const route = "/roast" + samplePath();
    $("sourceLink").href = route + "/source.png?download=1" + (archived ? "&report=" + state.report.id : "");
    if (archived) {
        const base = route + "/reports/" + state.report.id;
        $("reportCsv").href = base + "/beans.csv";
        $("reportImage").href = base + "/overlay.png";
    }
}

async function selectPoint(point) {
    state.probe = await request(samplePath("/point"), "POST", {
        point, report: state.report?.id, settings: state.result.settings,
    });
    state.selected = state.probe.bean;
    $("viewerStatus").textContent = tooltip();
    await suggestSampling();
    render();
}

async function suggestSampling() {
    state.sampling = null;
    if (!state.selected) { renderSampling(); return; }
    try {
        state.sampling = await request(samplePath("/sampling"), "POST", {
            bean: state.selected, report: state.report?.id, settings: state.result.settings,
        });
    } catch (error) {
        // The selected bean no longer exists under the current crop or separator.
        state.selected = null;
        state.probe = null;
    }
}
function clearSelection() {
    state.probe = null;
    state.selected = null;
    state.sampling = null;
    state.picking = false;
    state.corner = null;
    $("crop").textContent = "Set crop";
}

async function refresh(settings) {
    state.result = await request(samplePath("/inspect"), "POST", {settings});
    if (state.selected) await suggestSampling();
    render();
}

function toggleBean(id) {
    const settings = state.result.settings;
    const exclude = new Set(settings.exclude);
    if (exclude.has(id)) exclude.delete(id);
    else exclude.add(id);
    return refresh({...settings, exclude: [...exclude]});
}

async function openSample(id, samples) {
    const available = samples || await request("/samples");
    const sample = available.find(entry => entry.id === id) || available[0];
    if (!sample) return;
    const route = "/samples/" + sample.id;
    const photo = new Image();
    photo.src = "/roast" + route + "/source.png";
    const [result] = await Promise.all([request(route + "/inspect", "POST", {}), photo.decode()]);
    state.sample = sample;
    state.result = result;
    state.report = null;
    state.photo = photo;
    clearSelection();
    $("canvas").width = sample.width;
    $("canvas").height = sample.height;
    $("sampleList").replaceChildren(...available.map(entry => firstOption(entry.title, entry.id)));
    $("sampleList").value = sample.id;
    const provenance = sample.synthetic ? "Synthetic · " : sample.source.prepared ? "Prepared · " : "";
    $("photoInfo").textContent = provenance + sample.width + " × " + sample.height + " px";
    $("desk").hidden = false;
    $("empty").hidden = true;
    localStorage.setItem("roastdesk-sample", sample.id);
    render();
}

async function openReport(id) {
    if (!id) {
        await openSample(state.sample.id);
        return;
    }
    state.report = await request(samplePath("/reports/" + id));
    state.result = state.report;
    clearSelection();
    render();
}

$("demo").onclick = run(async () => {
    const sample = await request("/demo", "POST", {});
    await openSample(sample.id);
});
$("add").onclick = () => $("importDialog").showModal();
$("cancelImport").onclick = () => $("importDialog").close();
$("importForm").onsubmit = run(async () => {
    const sample = await request("/samples", "POST", new FormData($("importForm")));
    $("importDialog").close();
    $("importForm").reset();
    await openSample(sample.id);
});
$("sampleList").onchange = run(event => openSample(event.target.value));
$("reportList").onchange = run(event => openReport(event.target.value));
$("live").onclick = run(() => openReport(""));
$("original").onclick = () => {
    state.showMarks = !state.showMarks;
    $("original").textContent = state.showMarks ? "Hide marks" : "Show marks";
    $("original").setAttribute("aria-pressed", String(!state.showMarks));
    draw();
};
$("crop").onclick = () => {
    state.picking = !state.picking;
    state.corner = null;
    $("crop").textContent = state.picking ? "Cancel crop" : "Set crop";
    $("viewerStatus").textContent = tooltip();
    draw();
};
$("showExcluded").onchange = () => {
    draw();
    beanTable();
};
$("adoptSampling").onclick = run(async () => {
    if (!state.sampling) return;
    state.sample = await request(samplePath("/sampling"), "PUT", {
        bean: state.sampling.bean, settings: state.result.settings, revision: state.sample.revision,
    });
    await refresh(state.sample.settings);
    draw();
    notice("Sampling area adopted. This bean now uses only the retained source pixels.");
});
$("restoreSampling").onclick = run(async () => {
    if (!state.sampling) return;
    const bean = state.sampling.bean;
    state.sample = await request(samplePath("/sampling/" + encodeURIComponent(bean)) +
        "?revision=" + state.sample.revision, "DELETE");
    await refresh(state.sample.settings);
    notice("Whole bean restored.");
});
$("closeSampling").onclick = () => {
    state.sampling = null;
    renderSampling();
    draw();
};
$("canvas").onclick = run(async event => {
    const point = renderedPosition(event);
    if (!point) return;
    if (!state.picking) {
        await selectPoint(point);
    } else if (!state.corner) {
        state.corner = point;
        $("viewerStatus").textContent = tooltip();
        draw();
    } else {
        const [x, y] = state.corner;
        const [u, v] = point;
        const box = [Math.min(x, u), Math.min(y, v), Math.max(x, u) + 1, Math.max(y, v) + 1];
        await refresh({...state.result.settings, box, exclude: []});
        clearSelection();
        render();
    }
});
$("settings").onsubmit = run(async () => {
    if (!$("settings").reportValidity()) return;
    const settings = inputs();
    clearSelection();
    await refresh(settings);
});
$("saveSetup").onclick = run(async () => {
    if (!$("settings").reportValidity()) return;
    const settings = inputs();
    state.sample = await request(samplePath("/settings"), "PUT", {settings, revision: state.sample.revision});
    clearSelection();
    await refresh(state.sample.settings);
    notice("Sampling setup saved.");
});
$("saveReport").onclick = run(async () => {
    const saved = await request(samplePath("/reports"), "POST", {
        settings: state.result.settings, revision: state.sample.revision,
    });
    state.sample = saved.sample;
    state.result = state.report = saved.report;
    clearSelection();
    render();
    notice("Inspection saved.");
});

run(() => openSample(localStorage.getItem("roastdesk-sample")))();
