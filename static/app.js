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
        if (data.code === 200 && data.data?.access_token) {
            setAccessToken(data.data.access_token);
            return data.data.access_token;
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
            
            if (data.data?.access_token) {
                setAccessToken(data.data.access_token);
                if (data.data.refresh_token) {
                    setRefreshToken(data.data.refresh_token);
                }
                if (data.data.user) {
                    setUserInfo(data.data.user);
                }
                
                window.location.href = "/";
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
            
            if (data.data?.userId) {
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
    } catch {
        window.location.href = "/login";
    }
}

async function renderJobList() {
    const jobList = document.getElementById("job-list");
    if (!jobList) return;
    
    try {
        const data = await fetchJSON(`${API_BASE}/jobs`);
        const jobs = data.data?.jobs || [];
        
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
        const job = jobData.data?.job;
        
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
            const report = reportData.data?.report;
            
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

document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("login-form")) {
        handleLogin();
    } else if (document.getElementById("register-form")) {
        handleRegister();
    } else if (document.getElementById("main-app")) {
        checkAuthAndInit();
        handleLogout();
    }
});