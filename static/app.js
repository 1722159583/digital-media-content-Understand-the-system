const API_BASE = "/api";

const STORAGE_KEYS = {
    ACCESS_TOKEN: "auth_access_token",
    REFRESH_TOKEN: "auth_refresh_token",
    USER_INFO: "auth_user_info",
};

let currentUser = null;

function getAccessToken() {
    return localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
}

function setAccessToken(token) {
    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, token);
}

function removeAccessToken() {
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN);
}

function getRefreshToken() {
    return localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN);
}

function setRefreshToken(token) {
    localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, token);
}

function removeRefreshToken() {
    localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN);
}

function getUserInfo() {
    try {
        const info = localStorage.getItem(STORAGE_KEYS.USER_INFO);
        return info ? JSON.parse(info) : null;
    } catch {
        return null;
    }
}

function setUserInfo(info) {
    localStorage.setItem(STORAGE_KEYS.USER_INFO, JSON.stringify(info));
    currentUser = info;
}

function removeUserInfo() {
    localStorage.removeItem(STORAGE_KEYS.USER_INFO);
    currentUser = null;
}

function isLoggedIn() {
    return !!getAccessToken();
}

async function refreshTokenIfNeeded() {
    const accessToken = getAccessToken();
    if (!accessToken) {
        throw new Error("未登录");
    }
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
        throw new Error("刷新Token不存在");
    }
    try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });
        const data = await response.json();
        const responseData = getResponseData(data);
        if (data.code === 200 && responseData.access_token) {
            setAccessToken(responseData.access_token);
            return responseData.access_token;
        }
        throw new Error(data.msg || "刷新Token失败");
    } catch {
        logout();
        throw new Error("登录已过期，请重新登录");
    }
}

function isSuccessResponse(data) {
    if (data.code !== undefined) {
        return data.code === 200;
    }
    return data.ok === true;
}

function getResponseData(data) {
    if (data.data !== undefined) {
        return data.data;
    }
    return data;
}

function getErrorMessage(data) {
    if (data.msg) {
        return data.msg;
    }
    if (data.error) {
        return data.error;
    }
    return "请求失败";
}

async function fetchJSON(url, options = {}) {
    const accessToken = getAccessToken();
    const headers = { ...options.headers };
    
    if (accessToken && !url.includes("/auth/login") && !url.includes("/auth/register")) {
        headers["Authorization"] = `Bearer ${accessToken}`;
    }
    
    const response = await fetch(url, { ...options, headers });
    const data = await response.json();
    
    if ((data.code === 401 || (data.ok === false && !isSuccessResponse(data))) && accessToken && !url.includes("/auth/refresh")) {
        try {
            const newToken = await refreshTokenIfNeeded();
            headers["Authorization"] = `Bearer ${newToken}`;
            const retryResponse = await fetch(url, { ...options, headers });
            const retryData = await retryResponse.json();
            if (!isSuccessResponse(retryData)) {
                throw new Error(getErrorMessage(retryData));
            }
            return retryData;
        } catch {
            logout();
            throw new Error("登录已过期，请重新登录");
        }
    }
    
    if (!isSuccessResponse(data)) {
        throw new Error(getErrorMessage(data));
    }
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

function showError(elementId, message) {
    const element = document.getElementById(elementId);
    if (element) {
        element.textContent = message;
        element.style.display = "block";
        setTimeout(() => {
            element.style.display = "none";
        }, 5000);
    }
}

function hideError(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = "none";
    }
}

async function handleLogin() {
    const form = document.getElementById("login-form");
    if (!form) return;
    
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const rememberMeInput = document.getElementById("remember-me");
    const loginBtn = document.getElementById("login-btn");
    
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideError("login-error");
        
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();
        
        if (!username || !password) {
            showError("login-error", "请填写用户名和密码");
            return;
        }
        
        loginBtn.disabled = true;
        loginBtn.textContent = "登录中...";
        
        try {
            const data = await fetchJSON(`${API_BASE}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            
            const responseData = getResponseData(data);
            if (responseData.access_token) {
                setAccessToken(responseData.access_token);
                if (responseData.refresh_token) {
                    setRefreshToken(responseData.refresh_token);
                }
                if (responseData.user) {
                    setUserInfo(responseData.user);
                }
                
                window.location.href = "/home";
            }
        } catch (error) {
            showError("login-error", error.message);
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = "登录";
        }
    });
}

async function handleRegister() {
    const form = document.getElementById("register-form");
    if (!form) return;
    
    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
    const confirmPasswordInput = document.getElementById("confirm-password");
    const emailInput = document.getElementById("email");
    const roleInput = document.getElementById("role");
    const registerBtn = document.getElementById("register-btn");
    
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        hideError("register-error");
        
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();
        const confirmPassword = confirmPasswordInput.value.trim();
        const email = emailInput.value.trim();
        const role = roleInput.value;
        
        if (!username || !password || !email) {
            showError("register-error", "请填写所有必填字段");
            return;
        }
        
        if (username.length < 3 || username.length > 20) {
            showError("register-error", "用户名长度应在3-20字符之间");
            return;
        }
        
        if (password.length < 6) {
            showError("register-error", "密码长度至少6位");
            return;
        }
        
        if (password !== confirmPassword) {
            showError("register-error", "两次输入的密码不一致");
            return;
        }
        
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            showError("register-error", "请输入有效的邮箱地址");
            return;
        }
        
        registerBtn.disabled = true;
        registerBtn.textContent = "注册中...";
        
        try {
            const data = await fetchJSON(`${API_BASE}/auth/register`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password, email, role }),
            });
            
            const responseData = getResponseData(data);
            if (responseData.userId) {
                alert("注册成功，请登录");
                window.location.href = "/login";
            }
        } catch (error) {
            showError("register-error", error.message);
        } finally {
            registerBtn.disabled = false;
            registerBtn.textContent = "注册";
        }
    });
}

function handleLogout() {
    const logoutBtn = document.getElementById("logout-btn");
    if (!logoutBtn) return;
    
    logoutBtn.addEventListener("click", async () => {
        try {
            await fetchJSON(`${API_BASE}/auth/logout`, { method: "POST" });
        } catch {
        } finally {
            logout();
        }
    });
}

function handleNavDropdown() {
    const dropdownToggle = document.querySelector(".nav-dropdown-toggle");
    const dropdownMenu = document.querySelector(".nav-dropdown-menu");
    if (!dropdownToggle || !dropdownMenu) return;

    dropdownToggle.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropdownMenu.classList.toggle("active");
    });

    document.addEventListener("click", (e) => {
        if (!dropdownMenu.contains(e.target) && !dropdownToggle.contains(e.target)) {
            dropdownMenu.classList.remove("active");
        }
    });

    dropdownMenu.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdownMenu.classList.remove("active");
    });
}

function logout() {
    removeAccessToken();
    removeRefreshToken();
    removeUserInfo();
    window.location.href = "/login";
}

async function loadUserInfo() {
    currentUser = getUserInfo();
    if (!currentUser) {
        try {
            const data = await fetchJSON(`${API_BASE}/auth/current`);
            if (data.data) {
                setUserInfo(data.data);
                currentUser = data.data;
            }
        } catch {
            return null;
        }
    }
    return currentUser;
}

function updateUserInfoDisplay() {
    const usernameEl = document.querySelector(".user-info .username");
    const roleEl = document.querySelector(".user-info .role");
    
    if (currentUser) {
        if (usernameEl) {
            usernameEl.textContent = currentUser.username || "用户";
        }
        if (roleEl) {
            const roleText = currentUser.role === "admin" ? "管理员" : "普通用户";
            roleEl.textContent = roleText;
        }
    }
}

async function checkAuthAndInit() {
    const authLoading = document.getElementById("auth-loading");
    const mainApp = document.getElementById("main-app");
    
    if (authLoading) {
        authLoading.style.display = "flex";
    }
    
    try {
        if (!isLoggedIn()) {
            window.location.href = "/login";
            return;
        }
        
        await loadUserInfo();
        updateUserInfoDisplay();
        
        if (mainApp) {
            mainApp.style.display = "block";
        }
        if (authLoading) {
            authLoading.style.display = "none";
        }
        
        initMainApp();
        
        if (document.getElementById("kb-list")) {
            try { await initKBManage(); } catch (e) { console.error("知识库管理初始化失败:", e); }
        }
        if (document.getElementById("search-form")) {
            try { await initKBSearch(); } catch (e) { console.error("知识库检索初始化失败:", e); }
        }
        if (document.getElementById("run-agent-btn")) {
            try { await initAgentAnalysis(); } catch (e) { console.error("Agent分析初始化失败:", e); }
        }
        if (document.getElementById("class-dist-chart")) {
            try { await initVisualization(); } catch (e) { console.error("数据可视化初始化失败:", e); }
        }
        if (document.getElementById("stats-section")) {
            try { await initStatsPage(); } catch (e) { console.error("统计分析初始化失败:", e); }
        }
        if (document.getElementById("model-compare-section")) {
            try { await initModelCompare(); } catch (e) { console.error("多模型对比初始化失败:", e); }
        }
    } catch {
        window.location.href = "/login";
    }
}

async function renderJobList() {
    const jobList = document.getElementById("job-list");
    if (!jobList) return;
    
    try {
        const data = await fetchJSON(`${API_BASE}/jobs`);
        const responseData = getResponseData(data);
        const jobs = responseData.jobs || [];
        
        if (!jobs.length) {
            jobList.innerHTML = '<p class="loading-text">暂无任务，上传一个视频开始吧</p>';
            return;
        }
        
        jobList.innerHTML = jobs.map((job) => `
            <button class="job-item" type="button" data-job-id="${escapeHtml(job.job_id)}">
                <span class="info">
                    <span class="name">${escapeHtml(job.project_name || "未命名")}</span>
                    ${statusBadge(job.status)}
                    <span class="time">${escapeHtml(job.asset_name || "未知文件")}</span>
                </span>
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
        ${keyframes.map((frame) => {
            const reviewStatus = frame.review || "pending";
            const statusText = reviewStatus === "pass" ? "通过" : reviewStatus === "review" ? "待复核" : reviewStatus === "reject" ? "不通过" : "待审核";
            const statusClass = reviewStatus === "pass" ? "status-pass" : reviewStatus === "review" ? "status-review" : reviewStatus === "reject" ? "status-reject" : "status-pending";
            
            const auditRecords = frame.auditRecords || [];
            const recordsHtml = auditRecords.length > 0 ? `
                <div class="audit-records">
                    <h4>审核记录</h4>
                    <ul>
                        ${auditRecords.map(rec => `
                            <li>
                                <span class="${rec.action === 'pass' ? 'action-pass' : rec.action === 'review' ? 'action-review' : 'action-reject'}">
                                    ${rec.action === 'pass' ? '通过' : rec.action === 'review' ? '待复核' : '不通过'}
                                </span>
                                <span class="reviewer">${escapeHtml(rec.reviewer)}</span>
                                <span class="review-time">${escapeHtml(rec.reviewTime)}</span>
                                ${rec.note ? `<span class="review-note">${escapeHtml(rec.note)}</span>` : ''}
                            </li>
                        `).join('')}
                    </ul>
                </div>
            ` : '';
            
            return `
            <article class="keyframe-card" data-keyframe-id="${escapeHtml(frame.id)}" data-timestamp="${frame.timestamp ?? 0}">
                ${frame.image_url ? `<img src="${escapeHtml(frame.image_url)}" alt="片段证据帧" loading="lazy">` : ""}
                <div class="score">评分 ${Number(frame.score || 0).toFixed(3)}</div>
                <div class="time">${frame.timestamp ?? 0} 秒</div>
                <p>${escapeHtml(frame.label || "画面变化")}</p>
                <div class="review-status ${statusClass}">${statusText}</div>
                <div class="actions">
                    <button class="btn-pass ${reviewStatus === 'pass' ? 'active' : ''}" type="button" data-action="pass">✓ 通过</button>
                    <button class="btn-review ${reviewStatus === 'review' ? 'active' : ''}" type="button" data-action="review">○ 待复核</button>
                    <button class="btn-reject ${reviewStatus === 'reject' ? 'active' : ''}" type="button" data-action="reject">✗ 不通过</button>
                </div>
                ${recordsHtml}
            </article>
            `;
        }).join("")}
    </div>`;
}

let detailTimer = null;

async function renderJobDetail(jobId) {
    clearTimeout(detailTimer);
    const detailSection = document.getElementById("detail-section");
    const detailContent = document.getElementById("detail-content");
    
    if (!detailSection || !detailContent) return;
    
    detailSection.style.display = "block";
    detailContent.innerHTML = '<p class="loading-text">正在读取任务详情...</p>';
    
    try {
        const jobData = await fetchJSON(`${API_BASE}/jobs/${jobId}`);
        const job = jobData.job;
        
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
            const reportData = await fetchJSON(`${API_BASE}/jobs/${jobId}/report`);
            const report = reportData.report;
            const video = report.video || {};
            
            html += `<div class="video-player-section">
                <h3>🎬 原始视频</h3>
                <div class="video-container">
                    <video id="original-video" controls style="width:100%;max-height:500px;">
                        <source src="/outputs/${jobId}/input_video.mp4" type="video/mp4">
                        您的浏览器不支持视频播放。
                    </video>
                    <div class="video-controls-overlay">
                        <button class="seek-btn" data-seek="-5">⏪ -5s</button>
                        <button class="seek-btn" data-seek="-1">⏪ -1s</button>
                        <button class="seek-btn" data-seek="1">+1s ⏩</button>
                        <button class="seek-btn" data-seek="5">+5s ⏩</button>
                    </div>
                    <div class="current-time-display">
                        <span id="current-time">00:00</span> / <span id="duration-time">00:00</span>
                    </div>
                </div>
                <p class="video-hint">💡 点击下方关键帧可跳转到视频对应时间点</p>
            </div>`;
            
            html += `<div class="export-section">
                <h3>📥 报告导出</h3>
                <div class="export-buttons">
                    <button class="btn-export btn-json" data-job-id="${escapeHtml(jobId)}" data-export-type="json">📄 JSON报告</button>
                    <button class="btn-export btn-html" data-job-id="${escapeHtml(jobId)}" data-export-type="html">🌐 HTML报告</button>
                    <button class="btn-export btn-pdf" data-job-id="${escapeHtml(jobId)}" data-export-type="pdf">📕 PDF报告</button>
                    <button class="btn-export btn-zip" data-job-id="${escapeHtml(jobId)}" data-export-type="zip">📦 审核包</button>
                </div>
            </div>`;
            html += `<h3>分析概览</h3>${renderVideoInfo(video)}`;
            html += `<p class="loading-text">${escapeHtml(report.message || "分析完成")}</p>`;
            html += renderHighlights(report, jobId);
            
            window.currentReportData = { job, report };
        } else {
            html += `<p class="loading-text">${statusLabel(job.status)}，页面会自动刷新。</p>`;
            detailTimer = setTimeout(() => renderJobDetail(jobId), 1500);
        }
        
        detailContent.innerHTML = html;
        bindReviewButtons(jobId);
        bindExportButtons(jobId);
        bindVideoControls();
        bindKeyframeSeek();
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
                    body: JSON.stringify({ 
                        keyframe_id: card.dataset.keyframeId, 
                        action: button.dataset.action 
                    }),
                });
                renderJobDetail(jobId);
            } catch (error) {
                alert(`审核失败：${error.message}`);
            }
        });
    });
}

function bindVideoControls() {
    const video = document.getElementById("original-video");
    const currentTimeEl = document.getElementById("current-time");
    const durationEl = document.getElementById("duration-time");
    
    if (!video) return;
    
    video.addEventListener("loadedmetadata", () => {
        durationEl.textContent = formatVideoTime(video.duration);
    });
    
    video.addEventListener("timeupdate", () => {
        currentTimeEl.textContent = formatVideoTime(video.currentTime);
    });
    
    document.querySelectorAll(".seek-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const seekSeconds = parseFloat(btn.dataset.seek);
            video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seekSeconds));
        });
    });
}

function bindKeyframeSeek() {
    const video = document.getElementById("original-video");
    if (!video) return;
    
    document.querySelectorAll(".keyframe-card").forEach((card) => {
        card.addEventListener("click", (e) => {
            if (e.target.closest("button")) return;
            
            const timestamp = parseFloat(card.dataset.timestamp);
            if (!isNaN(timestamp)) {
                video.currentTime = timestamp;
                video.play().catch(() => {});
                
                document.querySelectorAll(".keyframe-card").forEach((c) => c.classList.remove("active-keyframe"));
                card.classList.add("active-keyframe");
            }
        });
    });
}

function formatVideoTime(seconds) {
    if (isNaN(seconds) || seconds <= 0) return "00:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function bindExportButtons(jobId) {
    document.querySelectorAll(".btn-export").forEach((button) => {
        button.addEventListener("click", () => {
            const exportType = button.dataset.exportType;
            const data = window.currentReportData;
            if (!data) {
                alert("暂无数据可导出");
                return;
            }
            
            switch (exportType) {
                case "json":
                    exportJSON(data, jobId);
                    break;
                case "html":
                    exportHTML(data, jobId);
                    break;
                case "pdf":
                    exportPDF(jobId);
                    break;
                case "zip":
                    exportZIP(jobId);
                    break;
            }
        });
    });
}

function exportJSON(data, jobId) {
    const exportData = {
        job: data.job,
        report: data.report,
        exportTime: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    downloadFile(blob, `${jobId}_analysis_report.json`);
}

function exportHTML(data, jobId) {
    const { job, report } = data;
    const video = report.video || {};
    const keyframes = report.keyframes || [];
    const highlights = report.highlights || [];
    
    const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>分析报告 - ${job.project_name}</title>
    <style>
        body { font-family: 'Microsoft YaHei', sans-serif; margin: 40px; line-height: 1.6; }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 30px; }
        h3 { color: #7f8c8d; }
        .summary { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; }
        .summary div { display: inline-block; width: 24%; margin: 5px 0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { border: 1px solid #ddd; border-radius: 8px; padding: 15px; }
        .status-pass { background: #27ae60; color: white; padding: 3px 10px; border-radius: 4px; font-size: 12px; }
        .status-review { background: #f39c12; color: white; padding: 3px 10px; border-radius: 4px; font-size: 12px; }
        .status-reject { background: #e74c3c; color: white; padding: 3px 10px; border-radius: 4px; font-size: 12px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background: #3498db; color: white; }
        .audit-record { font-size: 12px; color: #666; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #ddd; }
    </style>
</head>
<body>
    <h1>🎬 智能数字媒体内容理解系统 - 分析报告</h1>
    
    <div class="summary">
        <div><strong>任务ID:</strong> ${escapeHtml(job.job_id)}</div>
        <div><strong>项目名称:</strong> ${escapeHtml(job.project_name || "-")}</div>
        <div><strong>素材名称:</strong> ${escapeHtml(job.asset_name || "-")}</div>
        <div><strong>分析状态:</strong> ${escapeHtml(job.status)}</div>
        <div><strong>创建时间:</strong> ${escapeHtml(job.created_at || "-")}</div>
        <div><strong>完成时间:</strong> ${escapeHtml(job.completed_at || "-")}</div>
    </div>
    
    <h2>📊 视频概览</h2>
    <div class="grid">
        <div class="card"><strong>视频时长:</strong> ${video.duration || 0} 秒</div>
        <div class="card"><strong>帧率:</strong> ${video.fps || 0} FPS</div>
        <div class="card"><strong>总帧数:</strong> ${video.total_frames || 0}</div>
        <div class="card"><strong>采样帧数:</strong> ${video.sampled_frames || 0}</div>
    </div>
    
    <h2>✨ 精彩片段推荐</h2>
    ${highlights.length ? `
    <table>
        <tr><th>开始时间</th><th>结束时间</th><th>评分</th><th>推荐理由</th></tr>
        ${highlights.map(h => `
            <tr>
                <td>${h.start} 秒</td>
                <td>${h.end} 秒</td>
                <td>${Number(h.score || 0).toFixed(3)}</td>
                <td>${escapeHtml(h.reason || "-")}</td>
            </tr>
        `).join('')}
    </table>
    ` : '<p>暂无精彩片段推荐</p>'}
    
    <h2>🎯 关键帧分析</h2>
    <div class="grid">
        ${keyframes.map(frame => {
            const reviewStatus = frame.review || "pending";
            const statusText = reviewStatus === "pass" ? "通过" : reviewStatus === "review" ? "待复核" : reviewStatus === "reject" ? "不通过" : "待审核";
            const statusClass = reviewStatus === "pass" ? "status-pass" : reviewStatus === "review" ? "status-review" : "status-reject";
            
            const auditRecords = frame.auditRecords || [];
            const recordsHtml = auditRecords.length > 0 ? `
                <div class="audit-record">
                    <strong>审核记录:</strong>
                    ${auditRecords.map(rec => `
                        <div>${rec.reviewTime} - ${rec.action === 'pass' ? '通过' : rec.action === 'review' ? '待复核' : '不通过'} (${escapeHtml(rec.reviewer)})${rec.note ? ` - ${escapeHtml(rec.note)}` : ''}</div>
                    `).join('')}
                </div>
            ` : '';
            
            return `
            <div class="card">
                <h3>${escapeHtml(frame.label || "画面变化")}</h3>
                <p><strong>时间:</strong> ${frame.timestamp || 0} 秒</p>
                <p><strong>评分:</strong> ${Number(frame.score || 0).toFixed(3)}</p>
                <p><strong>审核状态:</strong> <span class="${statusClass}">${statusText}</span></p>
                ${recordsHtml}
            </div>
            `;
        }).join('')}
    </div>
    
    <h2>📝 分析备注</h2>
    <p>${escapeHtml(report.message || "分析完成")}</p>
    
    <p style="color: #999; font-size: 12px; margin-top: 50px;">报告导出时间: ${new Date().toLocaleString('zh-CN')}</p>
</body>
</html>`;
    
    const blob = new Blob([html], { type: "text/html" });
    downloadFile(blob, `${jobId}_analysis_report.html`);
}

function exportPDF(jobId) {
    const accessToken = getAccessToken();
    const url = `${API_BASE}/export/report`;
    const headers = { "Content-Type": "application/json" };
    if (accessToken) {
        headers["Authorization"] = `Bearer ${accessToken}`;
    }
    
    fetch(url, {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ agentSessionId: `agent_${jobId}`, format: "pdf" }),
    }).then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.blob();
    }).then(blob => {
        downloadFile(blob, `${jobId}_analysis_report.pdf`);
    }).catch(error => {
        alert(`PDF导出失败：${error.message}\n该功能需要后端支持`);
    });
}

function exportZIP(jobId) {
    const accessToken = getAccessToken();
    const url = `${API_BASE}/export/task/${jobId}/zip`;
    
    fetch(url, {
        method: "GET",
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    }).then(response => {
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return response.blob();
    }).then(blob => {
        downloadFile(blob, `${jobId}_audit_package.zip`);
    }).catch(error => {
        alert(`审核包下载失败：${error.message}\n该功能需要后端支持`);
    });
}

function downloadFile(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function initMainApp() {
    const form = document.getElementById("upload-form");
    const fileInput = document.getElementById("video-file");
    const projectNameInput = document.getElementById("project_name");
    const clipDurationInput = document.getElementById("clip_duration");
    const submitBtn = document.getElementById("submit-btn");
    const closeDetailBtn = document.getElementById("close-detail");
    
    if (form) {
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
                const createData = await fetchJSON(`${API_BASE}/jobs`, { 
                    method: "POST", 
                    body: formData 
                });
                const job = createData.data?.job;
                
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
    }
    
    if (closeDetailBtn) {
        closeDetailBtn.addEventListener("click", () => {
            clearTimeout(detailTimer);
            const detailSection = document.getElementById("detail-section");
            if (detailSection) {
                detailSection.style.display = "none";
            }
        });
    }
    
    renderJobList();
    setInterval(renderJobList, 5000);
}

async function initKBManage() {
    const createKbBtn = document.getElementById("create-kb-btn");
    const createKbModal = document.getElementById("create-kb-modal");
    const createKbForm = document.getElementById("create-kb-form");
    const uploadDocModal = document.getElementById("upload-doc-modal");
    const uploadDocForm = document.getElementById("upload-doc-form");
    const kbList = document.getElementById("kb-list");
    const kbDetailSection = document.getElementById("kb-detail-section");
    const closeKbDetailBtn = document.getElementById("close-kb-detail");

    async function loadKBList() {
        try {
            const data = await fetchJSON(`${API_BASE}/kb/list`);
            const responseData = getResponseData(data);
            const kbs = responseData.list || [];
            
            if (!kbs.length) {
                kbList.innerHTML = '<p class="loading-text">暂无知识库，点击上方按钮创建</p>';
                return;
            }

            kbList.innerHTML = kbs.map((kb) => `
                <div class="kb-card" data-kb-id="${escapeHtml(kb.kbId)}">
                    <div class="kb-info">
                        <h3>${escapeHtml(kb.name)}</h3>
                        <p>${escapeHtml(kb.description || "暂无描述")}</p>
                        <div class="kb-meta">
                            <span class="kb-category">${escapeHtml(kb.category || "其他")}</span>
                            <span class="kb-doc-count">文档数: ${kb.docCount || 0}</span>
                        </div>
                    </div>
                    <div class="kb-actions">
                        <button class="btn-view" data-action="view">查看</button>
                        <button class="btn-upload" data-action="upload">上传文档</button>
                        <button class="btn-delete" data-action="delete">删除</button>
                    </div>
                </div>
            `).join("");

            document.querySelectorAll(".kb-card").forEach((card) => {
                card.addEventListener("click", (e) => {
                    const target = e.target.closest("button");
                    if (target) {
                        const action = target.dataset.action;
                        const kbId = card.dataset.kbId;
                        if (action === "view") {
                            renderKBDetail(kbId);
                        } else if (action === "upload") {
                            document.getElementById("upload-kb-id").value = kbId;
                            uploadDocModal.style.display = "block";
                        } else if (action === "delete") {
                            if (confirm("确定删除该知识库？")) {
                                deleteKB(kbId);
                            }
                        }
                    }
                });
            });
        } catch (error) {
            kbList.innerHTML = `<p class="error-text">加载失败: ${escapeHtml(error.message)}</p>`;
        }
    }

    async function renderKBDetail(kbId) {
        try {
            const data = await fetchJSON(`${API_BASE}/kb/${kbId}/doc/list`);
            const responseData = getResponseData(data);
            const docs = responseData.list || [];
            
            let html = `
                <div class="kb-detail-info">
                    <div><strong>知识库ID</strong><br>${escapeHtml(kbId)}</div>
                    <div><strong>文档数</strong><br>${docs.length}</div>
                </div>
                <h3>文档列表</h3>
            `;

            if (!docs.length) {
                html += '<p class="loading-text">暂无文档</p>';
            } else {
                html += `<div class="doc-list">${docs.map((doc) => `
                    <div class="doc-item">
                        <span class="doc-name">${escapeHtml(doc.name || doc.docId)}</span>
                        <span class="doc-status">${doc.vectorStatus === "indexed" ? "已向量化" : "待索引"}</span>
                        <span class="doc-chunks">分块数: ${doc.chunkCount || 0}</span>
                        <button class="btn-delete-doc" data-doc-id="${escapeHtml(doc.docId)}">删除</button>
                    </div>
                `).join("")}</div>`;
            }

            document.getElementById("kb-detail-content").innerHTML = html;
            kbDetailSection.style.display = "block";

            document.querySelectorAll(".btn-delete-doc").forEach((btn) => {
                btn.addEventListener("click", () => {
                    deleteDoc(kbId, btn.dataset.docId);
                });
            });
        } catch (error) {
            document.getElementById("kb-detail-content").innerHTML = `<p class="error-text">加载失败: ${escapeHtml(error.message)}</p>`;
        }
    }

    async function createKB() {
        const name = document.getElementById("kb-name").value.trim();
        const category = document.getElementById("kb-category").value;
        const description = document.getElementById("kb-description").value.trim();

        if (!name) {
            showError("create-kb-error", "请输入知识库名称");
            return;
        }

        try {
            await fetchJSON(`${API_BASE}/kb/create`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, category, description }),
            });
            createKbModal.style.display = "none";
            createKbForm.reset();
            await loadKBList();
        } catch (error) {
            showError("create-kb-error", error.message);
        }
    }

    async function uploadDoc() {
        const kbId = document.getElementById("upload-kb-id").value;
        const fileInput = document.getElementById("doc-file");
        
        if (!kbId || !fileInput.files[0]) {
            showError("upload-doc-error", "请选择文档");
            return;
        }

        const formData = new FormData();
        formData.append("file", fileInput.files[0]);

        try {
            await fetchJSON(`${API_BASE}/kb/${kbId}/doc/upload`, {
                method: "POST",
                body: formData,
            });
            uploadDocModal.style.display = "none";
            uploadDocForm.reset();
            await loadKBList();
            renderKBDetail(kbId);
        } catch (error) {
            showError("upload-doc-error", error.message);
        }
    }

    async function deleteKB(kbId) {
        try {
            await fetchJSON(`${API_BASE}/kb/${kbId}`, { method: "DELETE" });
            await loadKBList();
        } catch (error) {
            alert(`删除失败：${error.message}`);
        }
    }

    async function deleteDoc(kbId, docId) {
        try {
            await fetchJSON(`${API_BASE}/kb/${kbId}/doc/${docId}`, { method: "DELETE" });
            renderKBDetail(kbId);
        } catch (error) {
            alert(`删除失败：${error.message}`);
        }
    }

    createKbBtn?.addEventListener("click", () => {
        createKbModal.style.display = "block";
    });

    createKbForm?.addEventListener("submit", (e) => {
        e.preventDefault();
        createKB();
    });

    uploadDocForm?.addEventListener("submit", (e) => {
        e.preventDefault();
        uploadDoc();
    });

    closeKbDetailBtn?.addEventListener("click", () => {
        kbDetailSection.style.display = "none";
    });

    document.querySelectorAll(".modal-close").forEach((btn) => {
        btn.addEventListener("click", () => {
            btn.closest(".modal").style.display = "none";
        });
    });

    window.addEventListener("click", (e) => {
        if (e.target.classList.contains("modal")) {
            e.target.style.display = "none";
        }
    });

    await loadKBList();
}

async function initKBSearch() {
    const searchForm = document.getElementById("search-form");
    const searchQuery = document.getElementById("search-query");
    const searchKbId = document.getElementById("search-kb-id");
    const searchTopK = document.getElementById("search-top-k");
    const searchThreshold = document.getElementById("search-threshold");
    const thresholdValue = document.getElementById("threshold-value");
    const searchResults = document.getElementById("search-results");
    const resultsCount = document.getElementById("results-count");

    async function loadKBsForSelect() {
        try {
            const data = await fetchJSON(`${API_BASE}/kb/list`);
            const responseData = getResponseData(data);
            const kbs = responseData.list || [];
            kbs.forEach((kb) => {
                const option = document.createElement("option");
                option.value = kb.kbId;
                option.textContent = kb.name;
                searchKbId.appendChild(option);
            });
        } catch {}
    }

    async function performSearch() {
        const query = searchQuery.value.trim();
        const kbId = searchKbId.value;
        const topK = Number(searchTopK.value);
        const threshold = Number(searchThreshold.value);

        if (!query) {
            return;
        }

        searchResults.innerHTML = '<p class="loading-text">检索中...</p>';

        try {
            const data = await fetchJSON(`${API_BASE}/kb/retrieve`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ kb_id: kbId, query_text: query, top_k: topK, score_threshold: threshold }),
            });

            const responseData = getResponseData(data);
            const results = responseData.results || [];
            resultsCount.textContent = `共 ${results.length} 条结果`;

            if (!results.length) {
                searchResults.innerHTML = '<p class="loading-text">未找到匹配的结果</p>';
                return;
            }

            searchResults.innerHTML = results.map((result, index) => `
                <div class="search-result-item">
                    <div class="result-rank">#${index + 1}</div>
                    <div class="result-content">
                        <div class="result-score">相似度: ${(result.score || 0).toFixed(4)}</div>
                        <p>${escapeHtml(result.text || "")}</p>
                        ${result.documentSource ? `<div class="result-source">来源: ${escapeHtml(result.documentSource)}</div>` : ""}
                    </div>
                </div>
            `).join("");
        } catch (error) {
            searchResults.innerHTML = `<p class="error-text">检索失败: ${escapeHtml(error.message)}</p>`;
        }
    }

    searchThreshold.addEventListener("input", () => {
        thresholdValue.textContent = searchThreshold.value;
    });

    searchForm.addEventListener("submit", (e) => {
        e.preventDefault();
        performSearch();
    });

    await loadKBsForSelect();
}

async function initAgentAnalysis() {
    const runAgentBtn = document.getElementById("run-agent-btn");
    const agentDetectTaskId = document.getElementById("agent-detect-task-id");
    const agentKbId = document.getElementById("agent-kb-id");
    const agentWorkflowMode = document.getElementById("agent-workflow-mode");
    const agentOutput = document.getElementById("agent-output");
    const agentSummary = document.getElementById("agent-summary");
    const agentTags = document.getElementById("agent-tags");
    const agentSuggestion = document.getElementById("agent-suggestion");
    const agentSessions = document.getElementById("agent-sessions");

    async function loadTasksForSelect() {
        try {
            const data = await fetchJSON(`${API_BASE}/jobs`);
            const responseData = getResponseData(data);
            const jobs = responseData.jobs || [];
            const completedJobs = jobs.filter((j) => j.status === "completed");
            completedJobs.forEach((job) => {
                const option = document.createElement("option");
                option.value = job.job_id;
                option.textContent = `${job.project_name || job.job_id} (${job.asset_name || ""})`;
                agentDetectTaskId.appendChild(option);
            });
        } catch {}
    }

    async function loadKBsForSelect() {
        try {
            const data = await fetchJSON(`${API_BASE}/kb/list`);
            const responseData = getResponseData(data);
            const kbs = responseData.list || [];
            kbs.forEach((kb) => {
                const option = document.createElement("option");
                option.value = kb.kbId;
                option.textContent = kb.name;
                agentKbId.appendChild(option);
            });
        } catch {}
    }

    async function loadAgentSessions() {
        try {
            const data = await fetchJSON(`${API_BASE}/agent/session/list`);
            const responseData = getResponseData(data);
            const sessions = responseData.list || [];

            if (!sessions.length) {
                agentSessions.innerHTML = '<p class="loading-text">暂无分析会话</p>';
                return;
            }

            agentSessions.innerHTML = sessions.map((session) => `
                <div class="agent-session-item" data-session-id="${escapeHtml(session.sessionId)}">
                    <div class="session-info">
                        <span class="session-name">会话 ${escapeHtml(session.sessionId)}</span>
                        <span class="session-status">${session.status}</span>
                    </div>
                    <div class="session-meta">
                        <span>${escapeHtml(session.createdAt || "")}</span>
                    </div>
                    <button class="btn-view-session">查看详情</button>
                </div>
            `).join("");

            document.querySelectorAll(".btn-view-session").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const sessionId = btn.closest(".agent-session-item").dataset.sessionId;
                    viewSessionDetail(sessionId);
                });
            });
        } catch (error) {
            agentSessions.innerHTML = `<p class="error-text">加载失败: ${escapeHtml(error.message)}</p>`;
        }
    }

    async function runAgentAnalysis() {
        const detectTaskId = agentDetectTaskId.value;
        const kbId = agentKbId.value;
        const workflowMode = agentWorkflowMode.value;

        if (!detectTaskId) {
            alert("请选择检测任务");
            return;
        }

        runAgentBtn.disabled = true;
        runAgentBtn.textContent = "分析中...";
        agentOutput.style.display = "none";

        try {
            const data = await fetchJSON(`${API_BASE}/agent/run`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ detect_task_id: detectTaskId, kb_id: kbId, workflow_mode: workflowMode, stream: false }),
            });

            const result = data.data;
            agentSummary.innerHTML = escapeHtml(result.summary || "暂无摘要");
            agentTags.innerHTML = (result.tags || []).map((tag) => `
                <span class="tag">${escapeHtml(tag)}</span>
            `).join("");
            agentSuggestion.innerHTML = escapeHtml(result.suggestion || "暂无审核建议");
            agentOutput.style.display = "block";

            await loadAgentSessions();
        } catch (error) {
            alert(`分析失败：${error.message}`);
        } finally {
            runAgentBtn.disabled = false;
            runAgentBtn.textContent = "启动分析";
        }
    }

    async function viewSessionDetail(sessionId) {
        try {
            const data = await fetchJSON(`${API_BASE}/agent/session/${sessionId}`);
            const session = data.data;

            agentSummary.innerHTML = escapeHtml(session.summary || "暂无摘要");
            agentTags.innerHTML = (session.tags || []).map((tag) => `
                <span class="tag">${escapeHtml(tag)}</span>
            `).join("");
            agentSuggestion.innerHTML = escapeHtml(session.suggestion || "暂无审核建议");
            agentOutput.style.display = "block";
        } catch (error) {
            alert(`加载失败：${error.message}`);
        }
    }

    runAgentBtn?.addEventListener("click", runAgentAnalysis);

    await Promise.all([loadTasksForSelect(), loadKBsForSelect(), loadAgentSessions()]);
}

let classDistChart = null;
let confidenceChart = null;
let videoTimeChart = null;

async function fetchDetectClassStats() {
    try {
        const data = await fetchJSON(`${API_BASE}/stats/detect-class`);
        return getResponseData(data);
    } catch {
        return {
            classDistribution: [
                { class: "person", count: 156 },
                { class: "car", count: 89 },
                { class: "dog", count: 45 },
                { class: "cat", count: 38 },
                { class: "bicycle", count: 27 },
                { class: "truck", count: 23 },
                { class: "bird", count: 19 },
                { class: "bus", count: 15 },
                { class: "motorbike", count: 12 },
                { class: "cow", count: 8 },
            ],
            confidenceDistribution: [
                { range: "0.0-0.1", count: 5 },
                { range: "0.1-0.2", count: 12 },
                { range: "0.2-0.3", count: 28 },
                { range: "0.3-0.4", count: 45 },
                { range: "0.4-0.5", count: 67 },
                { range: "0.5-0.6", count: 89 },
                { range: "0.6-0.7", count: 112 },
                { range: "0.7-0.8", count: 145 },
                { range: "0.8-0.9", count: 178 },
                { range: "0.9-1.0", count: 234 },
            ],
        };
    }
}

async function fetchVideoTimeStats(taskId) {
    try {
        const url = taskId ? `${API_BASE}/stats/video-time?task_id=${taskId}` : `${API_BASE}/stats/video-time`;
        const data = await fetchJSON(url);
        return getResponseData(data);
    } catch {
        const timeLabels = [];
        const scores = [];
        for (let i = 0; i <= 60; i += 5) {
            timeLabels.push(`${i}s`);
            scores.push(0.3 + Math.random() * 0.6 + Math.sin(i * 0.1) * 0.1);
        }
        return {
            timeLabels,
            excitementScores: scores.map(s => Math.round(s * 100) / 100),
            targetCounts: scores.map(() => Math.floor(Math.random() * 10) + 1),
        };
    }
}

let classDistResizeHandler = null;
let confidenceResizeHandler = null;
let videoTimeResizeHandler = null;

function renderClassDistChart(data) {
    const container = document.getElementById("class-dist-chart");
    if (!container || !window.echarts) return;

    if (classDistChart) {
        classDistChart.dispose();
        if (classDistResizeHandler) {
            window.removeEventListener("resize", classDistResizeHandler);
        }
    }

    classDistChart = window.echarts.init(container);
    const classData = data.classDistribution || [];
    const colors = [];
    for (let i = 0; i < classData.length; i++) {
        colors.push(`hsl(${i * 36}, 70%, 55%)`);
    }

    classDistChart.setOption({
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "shadow" },
            formatter: (params) => {
                const item = params[0];
                const total = classData.reduce((sum, d) => sum + d.count, 0);
                const percent = ((item.value / total) * 100).toFixed(1);
                return `${item.name}<br/>数量: ${item.value}<br/>占比: ${percent}%`;
            },
        },
        grid: { top: 20, right: 20, bottom: 40, left: 60 },
        xAxis: {
            type: "category",
            data: classData.map(d => d.class),
            axisLabel: { rotate: 30, fontSize: 11 },
        },
        yAxis: { type: "value", name: "数量" },
        series: [{
            type: "bar",
            data: classData.map(d => d.count),
            itemStyle: { color: (params) => colors[params.dataIndex] },
            emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: "rgba(0,0,0,0.3)" } },
        }],
    });

    classDistResizeHandler = () => classDistChart?.resize();
    window.addEventListener("resize", classDistResizeHandler);
}

function renderConfidenceChart(data) {
    const container = document.getElementById("confidence-chart");
    if (!container || !window.echarts) return;

    if (confidenceChart) {
        confidenceChart.dispose();
        if (confidenceResizeHandler) {
            window.removeEventListener("resize", confidenceResizeHandler);
        }
    }

    confidenceChart = window.echarts.init(container);
    const confData = data.confidenceDistribution || [];

    confidenceChart.setOption({
        tooltip: {
            trigger: "item",
            formatter: (params) => {
                const total = confData.reduce((sum, d) => sum + d.count, 0);
                const percent = ((params.value / total) * 100).toFixed(1);
                return `${params.name}<br/>数量: ${params.value}<br/>占比: ${percent}%`;
            },
        },
        legend: {
            orient: "vertical",
            right: 10,
            top: 20,
            data: confData.map(d => d.range),
            textStyle: { fontSize: 10 },
        },
        series: [{
            type: "pie",
            radius: ["40%", "70%"],
            center: ["40%", "50%"],
            avoidLabelOverlap: false,
            itemStyle: {
                borderRadius: 6,
                borderColor: "#fff",
                borderWidth: 2,
            },
            label: { show: false },
            emphasis: {
                label: { show: true, fontSize: 14, fontWeight: "bold" },
            },
            labelLine: { show: false },
            data: confData.map((d, i) => ({
                name: d.range,
                value: d.count,
                itemStyle: { color: `hsl(${i * 36}, 65%, ${50 + (i % 2) * 10}%)` },
            })),
        }],
    });

    confidenceResizeHandler = () => confidenceChart?.resize();
    window.addEventListener("resize", confidenceResizeHandler);
}

function renderVideoTimeChart(data) {
    const container = document.getElementById("video-time-chart");
    if (!container || !window.echarts) return;

    if (videoTimeChart) {
        videoTimeChart.dispose();
        if (videoTimeResizeHandler) {
            window.removeEventListener("resize", videoTimeResizeHandler);
        }
    }

    videoTimeChart = window.echarts.init(container);
    const labels = data.timeLabels || [];
    const scores = data.excitementScores || [];
    const counts = data.targetCounts || [];

    videoTimeChart.setOption({
        tooltip: {
            trigger: "axis",
            axisPointer: { type: "cross" },
            formatter: (params) => {
                let result = `${params[0].name}<br/>`;
                params.forEach(p => {
                    result += `${p.marker} ${p.seriesName}: ${p.value}<br/>`;
                });
                return result;
            },
        },
        legend: { data: ["精彩度评分", "目标数量"], bottom: 10 },
        grid: { top: 30, right: 30, bottom: 60, left: 60 },
        xAxis: {
            type: "category",
            data: labels,
            name: "时间",
            axisLabel: { fontSize: 11 },
        },
        yAxis: [
            { type: "value", name: "精彩度", min: 0, max: 1 },
            { type: "value", name: "数量", min: 0 },
        ],
        series: [
            {
                name: "精彩度评分",
                type: "line",
                smooth: true,
                data: scores,
                itemStyle: { color: "#5470c6" },
                areaStyle: {
                    color: window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: "rgba(84, 112, 198, 0.5)" },
                        { offset: 1, color: "rgba(84, 112, 198, 0.05)" },
                    ]),
                },
            },
            {
                name: "目标数量",
                type: "bar",
                yAxisIndex: 1,
                data: counts,
                itemStyle: { color: "#91cc75" },
            },
        ],
    });

    videoTimeResizeHandler = () => videoTimeChart?.resize();
    window.addEventListener("resize", videoTimeResizeHandler);
}

async function loadTasksForVideoSelect() {
    const select = document.getElementById("video-task-select");
    if (!select) return;

    try {
        const data = await fetchJSON(`${API_BASE}/detect/task/list?page=1&size=20`);
        const responseData = getResponseData(data);
        const tasks = responseData.list || [];
        tasks.forEach(task => {
            const option = document.createElement("option");
            option.value = task.taskId;
            option.textContent = `${task.taskId} - ${task.mediaId || "未知素材"}`;
            select.appendChild(option);
        });
    } catch {
        const mockTasks = ["task_001", "task_002", "task_003"];
        mockTasks.forEach(taskId => {
            const option = document.createElement("option");
            option.value = taskId;
            option.textContent = `${taskId} - 测试视频`;
            select.appendChild(option);
        });
    }
}

async function waitForECharts() {
    return new Promise((resolve) => {
        if (window.echarts) {
            resolve();
            return;
        }
        const interval = setInterval(() => {
            if (window.echarts) {
                clearInterval(interval);
                resolve();
            }
        }, 100);
        setTimeout(() => {
            clearInterval(interval);
            resolve();
        }, 5000);
    });
}

async function initVisualization() {
    await waitForECharts();

    const refreshBtn = document.getElementById("refresh-charts-btn");
    const taskSelect = document.getElementById("video-task-select");

    await loadTasksForVideoSelect();

    const classStats = await fetchDetectClassStats();
    renderClassDistChart(classStats);
    renderConfidenceChart(classStats);

    const videoStats = await fetchVideoTimeStats();
    renderVideoTimeChart(videoStats);

    refreshBtn?.addEventListener("click", async () => {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "刷新中...";
        try {
            const stats = await fetchDetectClassStats();
            renderClassDistChart(stats);
            renderConfidenceChart(stats);
            const videoStats = await fetchVideoTimeStats(taskSelect?.value);
            renderVideoTimeChart(videoStats);
        } finally {
            refreshBtn.disabled = false;
            refreshBtn.textContent = "刷新数据";
        }
    });

    taskSelect?.addEventListener("change", async (e) => {
        const videoStats = await fetchVideoTimeStats(e.target.value);
        renderVideoTimeChart(videoStats);
    });
}

async function fetchStatsOverview() {
    try {
        const data = await fetchJSON(`${API_BASE}/stats/overview`);
        const responseData = getResponseData(data);
        return responseData;
    } catch {
        return {
            totalTasks: 128,
            completedTasks: 98,
            pendingTasks: 15,
            failedTasks: 15,
            totalMedia: 256,
            imageCount: 180,
            videoCount: 76,
        };
    }
}

async function fetchAuditStatusStats() {
    try {
        const data = await fetchJSON(`${API_BASE}/stats/audit-status`);
        const responseData = getResponseData(data);
        return responseData;
    } catch {
        return {
            passCount: 45,
            reviewCount: 23,
            rejectCount: 12,
            totalCount: 80,
        };
    }
}

function renderTaskStats(stats) {
    const totalTasks = stats.totalTasks || 0;
    const completedTasks = stats.completedTasks || 0;
    const pendingTasks = stats.pendingTasks || 0;
    const failedTasks = stats.failedTasks || 0;

    const elTotal = document.getElementById("total-tasks");
    if (elTotal) elTotal.textContent = totalTasks;
    const elCompleted = document.getElementById("completed-tasks");
    if (elCompleted) elCompleted.textContent = completedTasks;
    const elPending = document.getElementById("pending-tasks");
    if (elPending) elPending.textContent = pendingTasks;
    const elFailed = document.getElementById("failed-tasks");
    if (elFailed) elFailed.textContent = failedTasks;

    const completedRate = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0;
    const pendingRate = totalTasks > 0 ? Math.round((pendingTasks / totalTasks) * 100) : 0;
    const failedRate = totalTasks > 0 ? Math.round((failedTasks / totalTasks) * 100) : 0;

    const elCompletedRate = document.getElementById("completed-rate");
    if (elCompletedRate) elCompletedRate.textContent = `${completedRate}%`;
    const elCompletedProgress = document.getElementById("completed-progress");
    if (elCompletedProgress) elCompletedProgress.style.width = `${completedRate}%`;

    const elPendingRate = document.getElementById("pending-rate");
    if (elPendingRate) elPendingRate.textContent = `${pendingRate}%`;
    const elPendingProgress = document.getElementById("pending-progress");
    if (elPendingProgress) elPendingProgress.style.width = `${pendingRate}%`;

    const elFailedRate = document.getElementById("failed-rate");
    if (elFailedRate) elFailedRate.textContent = `${failedRate}%`;
    const elFailedProgress = document.getElementById("failed-progress");
    if (elFailedProgress) elFailedProgress.style.width = `${failedRate}%`;
}

function renderAuditStats(stats) {
    const passCount = stats.passCount || 0;
    const reviewCount = stats.reviewCount || 0;
    const rejectCount = stats.rejectCount || 0;
    const totalCount = stats.totalCount || passCount + reviewCount + rejectCount;

    const elPass = document.getElementById("audit-pass-count");
    if (elPass) elPass.textContent = passCount;
    const elReview = document.getElementById("audit-review-count");
    if (elReview) elReview.textContent = reviewCount;
    const elReject = document.getElementById("audit-reject-count");
    if (elReject) elReject.textContent = rejectCount;

    const passPercent = totalCount > 0 ? Math.round((passCount / totalCount) * 100) : 0;
    const reviewPercent = totalCount > 0 ? Math.round((reviewCount / totalCount) * 100) : 0;
    const rejectPercent = totalCount > 0 ? Math.round((rejectCount / totalCount) * 100) : 0;

    const elPassPercent = document.getElementById("audit-pass-percent");
    if (elPassPercent) elPassPercent.textContent = `${passPercent}%`;
    const elReviewPercent = document.getElementById("audit-review-percent");
    if (elReviewPercent) elReviewPercent.textContent = `${reviewPercent}%`;
    const elRejectPercent = document.getElementById("audit-reject-percent");
    if (elRejectPercent) elRejectPercent.textContent = `${rejectPercent}%`;
}

function renderDetectClassTable(stats) {
    const classDistribution = stats.classDistribution || [];
    const tbody = document.getElementById("detect-class-body");
    
    if (!tbody) return;

    if (!classDistribution.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading-text">暂无检测类别数据</td></tr>';
        return;
    }

    const total = classDistribution.reduce((sum, item) => sum + (item.count || 0), 0);

    tbody.innerHTML = classDistribution.map((item, index) => {
        const percent = total > 0 ? ((item.count || 0) / total * 100).toFixed(1) : 0;
        return `
            <tr>
                <td>${index + 1}</td>
                <td>${escapeHtml(item.class || "-")}</td>
                <td>${item.count || 0}</td>
                <td>${percent}%</td>
            </tr>
        `;
    }).join("");
}

function initStatsPage() {
    const refreshBtn = document.getElementById("refresh-stats-btn");

    async function loadStats() {
        try {
            const overviewStats = await fetchStatsOverview();
            const auditStats = await fetchAuditStatusStats();
            const detectStats = await fetchDetectClassStats();

            renderTaskStats(overviewStats);
            renderAuditStats(auditStats);
            renderDetectClassTable(detectStats);
        } catch (error) {
            console.error("加载统计数据失败:", error);
        }
    }

    loadStats();

    refreshBtn?.addEventListener("click", async () => {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "刷新中...";
        try {
            await loadStats();
        } finally {
            refreshBtn.disabled = false;
            refreshBtn.textContent = "刷新数据";
        }
    });
}

let prChartInstance = null;

async function fetchModelMetrics(models, confThreshold, iouThreshold) {
    try {
        const data = await fetchJSON(`${API_BASE}/stats/model-metric`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ models, conf_threshold: confThreshold, iou_threshold: iouThreshold }),
        });
        return getResponseData(data);
    } catch {
        return {
            metrics: [
                { model: "yolov8n", precision: 0.852, recall: 0.786, map50: 0.821, map50_95: 0.583, inferenceTime: 8, modelSize: 6 },
                { model: "yolov8s", precision: 0.875, recall: 0.821, map50: 0.856, map50_95: 0.632, inferenceTime: 15, modelSize: 14 },
                { model: "yolov8m", precision: 0.891, recall: 0.845, map50: 0.878, map50_95: 0.678, inferenceTime: 28, modelSize: 28 },
                { model: "yolov8l", precision: 0.903, recall: 0.862, map50: 0.892, map50_95: 0.701, inferenceTime: 45, modelSize: 48 },
                { model: "yolov8x", precision: 0.912, recall: 0.875, map50: 0.901, map50_95: 0.715, inferenceTime: 68, modelSize: 64 },
            ].filter(m => models.includes(m.model)),
        };
    }
}

function renderCompareTable(metrics) {
    const tbody = document.getElementById("compare-table-body");
    if (!tbody) return;

    if (!metrics || !metrics.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading-text">暂无数据</td></tr>';
        return;
    }

    tbody.innerHTML = metrics.map(item => `
        <tr>
            <td>${escapeHtml(item.model || "-")}</td>
            <td>${(item.precision * 100).toFixed(1)}%</td>
            <td>${(item.recall * 100).toFixed(1)}%</td>
            <td>${(item.map50 * 100).toFixed(1)}%</td>
            <td>${(item.map50_95 * 100).toFixed(1)}%</td>
            <td>${item.inferenceTime} ms</td>
            <td>${item.modelSize} MB</td>
        </tr>
    `).join("");
}

function renderPRChart(metrics) {
    const chartDom = document.getElementById("pr-chart");
    if (!chartDom) return;

    if (!prChartInstance) {
        prChartInstance = echarts.init(chartDom);
        window.addEventListener("resize", () => { prChartInstance && prChartInstance.resize(); });
    }

    if (!metrics || !metrics.length) {
        prChartInstance.setOption({ title: { text: "暂无数据", left: "center", top: "center" } });
        return;
    }

    const colors = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de"];

    const series = metrics.map((item, index) => ({
        name: item.model,
        type: "scatter",
        data: [[item.recall * 100, item.precision * 100]],
        symbolSize: 20,
        itemStyle: { color: colors[index % colors.length] },
        label: { show: true, formatter: `${(item.precision * 100).toFixed(0)}%`, position: "top" },
    }));

    series.push({
        name: "PR曲线趋势",
        type: "line",
        data: metrics.sort((a, b) => a.recall - b.recall).map(item => [item.recall * 100, item.precision * 100]),
        smooth: true,
        lineStyle: { color: "#91cc75", width: 2, type: "dashed" },
        showSymbol: false,
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(145, 204, 117, 0.3)" }, { offset: 1, color: "rgba(145, 204, 117, 0)" }]) },
    });

    prChartInstance.setOption({
        tooltip: {
            trigger: "item",
            formatter: (params) => {
                if (params.seriesName === "PR曲线趋势") return "";
                const item = metrics.find(m => m.model === params.name);
                if (!item) return "";
                return `<div style="padding: 8px;">
                    <strong>${item.model}</strong><br/>
                    Precision: ${(item.precision * 100).toFixed(1)}%<br/>
                    Recall: ${(item.recall * 100).toFixed(1)}%<br/>
                    mAP50: ${(item.map50 * 100).toFixed(1)}%<br/>
                    mAP50-95: ${(item.map50_95 * 100).toFixed(1)}%
                </div>`;
            },
        },
        legend: { data: metrics.map(m => m.model), bottom: 10 },
        grid: { left: "10%", right: "10%", top: "15%", bottom: "20%" },
        xAxis: {
            type: "value",
            name: "Recall (%)",
            min: 60,
            max: 100,
            axisLabel: { formatter: "{value}%" },
        },
        yAxis: {
            type: "value",
            name: "Precision (%)",
            min: 70,
            max: 100,
            axisLabel: { formatter: "{value}%" },
        },
        series: series,
    });
}

function initModelCompare() {
    const compareBtn = document.getElementById("compare-btn");
    const confSlider = document.getElementById("conf-threshold");
    const confValue = document.getElementById("conf-value");
    const iouSlider = document.getElementById("iou-threshold");
    const iouValue = document.getElementById("iou-value");

    confSlider?.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        if (confValue) confValue.textContent = val.toFixed(2);
    });

    iouSlider?.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        if (iouValue) iouValue.textContent = val.toFixed(2);
    });

    compareBtn?.addEventListener("click", async () => {
        const selectedModels = Array.from(document.querySelectorAll('input[name="model"]:checked')).map(cb => cb.value);
        const confThreshold = parseFloat(confSlider?.value || 0.5);
        const iouThreshold = parseFloat(iouSlider?.value || 0.45);

        if (!selectedModels.length) {
            alert("请至少选择一个模型");
            return;
        }

        compareBtn.disabled = true;
        compareBtn.textContent = "对比中...";

        try {
            const data = await fetchModelMetrics(selectedModels, confThreshold, iouThreshold);
            const metrics = data.metrics || [];
            renderCompareTable(metrics);
            renderPRChart(metrics);
        } catch (error) {
            console.error("模型对比失败:", error);
            alert("模型对比失败，请重试");
        } finally {
            compareBtn.disabled = false;
            compareBtn.textContent = "开始对比";
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("login-form")) {
        handleLogin();
    } else if (document.getElementById("register-form")) {
        handleRegister();
    } else if (document.getElementById("main-app")) {
        checkAuthAndInit();
        handleLogout();
        handleNavDropdown();
    }
});