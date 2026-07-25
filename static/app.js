const API_BASE = "/api";

const form = document.getElementById("upload-form");
const fileInput = document.getElementById("video-file");
const projectNameInput = document.getElementById("project_name");
const clipDurationInput = document.getElementById("clip_duration");
const submitBtn = document.getElementById("submit-btn");
const jobList = document.getElementById("job-list");
const detailSection = document.getElementById("detail-section");
const detailContent = document.getElementById("detail-content");
const closeDetailBtn = document.getElementById("close-detail");
let detailTimer = null;

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "请求失败");
    return data;
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}

function formatTime(value) {
    return value ? new Date(value).toLocaleString("zh-CN") : "-";
}

function statusLabel(status) {
    return ({ created: "已创建", queued: "排队中", running: "处理中", completed: "已完成", failed: "失败" })[status] || status;
}

function statusBadge(status) {
    return `<span class="status status-${escapeHtml(status)}">${statusLabel(status)}</span>`;
}

async function renderJobList() {
    try {
        const { jobs } = await fetchJSON(`${API_BASE}/jobs`);
        if (!jobs.length) {
            jobList.innerHTML = '<p class="loading-text">暂无任务，上传一个视频开始吧</p>';
            return;
        }
        jobList.innerHTML = jobs.map((job) => `
            <button class="job-item" type="button" data-job-id="${escapeHtml(job.job_id)}">
                <span class="info"><span class="name">${escapeHtml(job.project_name || "未命名")}</span>
                ${statusBadge(job.status)}<span class="time">${escapeHtml(job.asset_name || "未知文件")}</span></span>
                <span class="time">${formatTime(job.created_at)}</span>
            </button>
        `).join("");
        document.querySelectorAll(".job-item").forEach((element) => {
            element.addEventListener("click", () => renderJobDetail(element.dataset.jobId));
        });
    } catch (error) {
        jobList.innerHTML = `<p class="error-text">加载失败: ${escapeHtml(error.message)}</p>`;
    }
}

function renderVideoInfo(video) {
    return `<div class="report-grid">
        <div><strong>视频时长</strong><br>${video.duration ?? 0} 秒</div>
        <div><strong>帧率</strong><br>${video.fps ?? 0} FPS</div>
        <div><strong>总帧数</strong><br>${video.total_frames ?? 0}</div>
        <div><strong>采样帧</strong><br>${video.sampled_frames ?? 0}</div>
    </div>`;
}

function renderHighlights(report, jobId) {
    const keyframes = report.keyframes || [];
    if (!keyframes.length) return '<p class="loading-text">本次分析未筛选出高光片段。</p>';
    return `<h3>推荐精彩片段</h3><div class="keyframes-grid" data-job-id="${escapeHtml(jobId)}">
        ${keyframes.map((frame) => `
            <article class="keyframe-card" data-keyframe-id="${escapeHtml(frame.id)}">
                ${frame.image_url ? `<img src="${escapeHtml(frame.image_url)}" alt="片段证据帧" loading="lazy">` : ""}
                <div class="score">评分 ${Number(frame.score || 0).toFixed(3)}</div>
                <div class="time">${frame.timestamp ?? 0} 秒</div>
                <p>${escapeHtml(frame.label || "画面变化")}</p>
                <div class="actions">
                    <button class="kept" type="button" data-action="keep">保留</button>
                    <button class="ignored" type="button" data-action="ignore">忽略</button>
                </div>
                <small>审核：${escapeHtml(frame.review || "pending")}</small>
            </article>
        `).join("")}
    </div>`;
}

async function renderJobDetail(jobId) {
    clearTimeout(detailTimer);
    detailSection.style.display = "block";
    detailContent.innerHTML = '<p class="loading-text">正在读取任务详情...</p>';
    try {
        const { job } = await fetchJSON(`${API_BASE}/jobs/${jobId}`);
        let html = `<div class="job-summary">
            <div><strong>任务 ID</strong><br>${escapeHtml(job.job_id)}</div>
            <div><strong>状态</strong><br>${statusBadge(job.status)}</div>
            <div><strong>项目</strong><br>${escapeHtml(job.project_name || "-")}</div>
            <div><strong>素材</strong><br>${escapeHtml(job.asset_name || "-")}</div>
            <div><strong>创建时间</strong><br>${formatTime(job.created_at)}</div>
            <div><strong>完成时间</strong><br>${formatTime(job.completed_at)}</div>
        </div>`;
        if (job.status === "failed") {
            html += `<p class="error-text">分析失败：${escapeHtml(job.error || "未知错误")}</p>`;
        } else if (job.status === "completed" && job.result_file) {
            const { report } = await fetchJSON(`${API_BASE}/jobs/${jobId}/report`);
            html += `<h3>分析概览</h3>${renderVideoInfo(report.video || {})}`;
            html += `<p class="loading-text">${escapeHtml(report.message || "分析完成")}</p>`;
            html += renderHighlights(report, jobId);
        } else {
            html += `<p class="loading-text">${statusLabel(job.status)}，页面会自动刷新。</p>`;
            detailTimer = setTimeout(() => renderJobDetail(jobId), 1500);
        }
        detailContent.innerHTML = html;
        bindReviewButtons(jobId);
    } catch (error) {
        detailContent.innerHTML = `<p class="error-text">加载详情失败：${escapeHtml(error.message)}</p>`;
    }
}

function bindReviewButtons(jobId) {
    document.querySelectorAll(".keyframe-card .actions button").forEach((button) => {
        button.addEventListener("click", async () => {
            const card = button.closest(".keyframe-card");
            try {
                await fetchJSON(`${API_BASE}/jobs/${jobId}/review`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ keyframe_id: card.dataset.keyframeId, action: button.dataset.action }),
                });
                renderJobDetail(jobId);
            } catch (error) {
                alert(`审核失败：${error.message}`);
            }
        });
    });
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!fileInput.files[0]) return;
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("project_name", projectNameInput.value || "未命名项目");
    formData.append("settings", JSON.stringify({ clip_duration: Number(clipDurationInput.value) || 6 }));
    submitBtn.disabled = true;
    submitBtn.textContent = "上传中...";
    try {
        const { job } = await fetchJSON(`${API_BASE}/jobs`, { method: "POST", body: formData });
        await fetchJSON(`${API_BASE}/jobs/${job.job_id}/analyze`, { method: "POST" });
        fileInput.value = "";
        await renderJobList();
        renderJobDetail(job.job_id);
    } catch (error) {
        alert(`创建失败：${error.message}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "创建任务";
    }
});

closeDetailBtn.addEventListener("click", () => {
    clearTimeout(detailTimer);
    detailSection.style.display = "none";
});

setInterval(renderJobList, 5000);
renderJobList();
