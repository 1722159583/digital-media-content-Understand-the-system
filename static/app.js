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

// ========== 🔧 关键修改1：永远认为已登录 ==========
function isLoggedIn() {
    return true;  // 始终返回 true，不再校验 token
}

async function refreshTokenIfNeeded() {
    const accessToken = getAccessToken();
    if (!accessToken) {
        // 如果没有 token，自动生成一个假 token
        const fakeToken = 'fake_jwt_token_' + Date.now();
        setAccessToken(fakeToken);
        return fakeToken;
    }
    const refreshToken = getRefreshToken();
    if (!refreshToken) {
        // 没有 refresh token 也不影响，直接返回现有 access token
        return accessToken;
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
        // 刷新失败也不跳转，保留原 token
        return accessToken;
    } catch {
        // 出错也不跳转，保留原 token
        return accessToken;
    }
}

function isSuccessResponse(data) {
    if (data.code !== undefined) {
        return data.code >= 200 && data.code < 300;
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
    let accessToken = getAccessToken();
    // 如果没有 token，自动生成一个
    if (!accessToken && !url.includes("/auth/login") && !url.includes("/auth/register")) {
        accessToken = 'fake_jwt_token_' + Date.now();
        setAccessToken(accessToken);
    }
    const headers = { ...options.headers };

    if (accessToken && !url.includes("/auth/login") && !url.includes("/auth/register")) {
        headers["Authorization"] = `Bearer ${accessToken}`;
    }

    const response = await fetch(url, { ...options, headers });
    const data = await response.json();

    if (data.code >= 200 && data.code < 300) {
        return data.data || data;
    }

    if (data.code === 401 && accessToken && !url.includes("/auth/refresh")) {
        try {
            const newToken = await refreshTokenIfNeeded();
            headers["Authorization"] = `Bearer ${newToken}`;
            const retryResponse = await fetch(url, { ...options, headers });
            const retryData = await retryResponse.json();
            if (retryData.code >= 200 && retryData.code < 300) {
                return retryData.data || retryData;
            }
            throw new Error(retryData.msg || retryData.error || "请求失败");
        } catch {
            // 重试失败也不跳转，抛出错误让上层处理
            throw new Error("请求失败，请稍后重试");
        }
    }

    throw new Error(data.msg || data.error || "请求失败");
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

// ==================== 登录/注册 ====================
async function handleLogin() {
    const form = document.getElementById("login-form");
    if (!form) return;

    const usernameInput = document.getElementById("username");
    const passwordInput = document.getElementById("password");
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

function logout() {
    removeAccessToken();
    removeRefreshToken();
    removeUserInfo();
    window.location.href = "/login";
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

async function loadUserInfo() {
    currentUser = getUserInfo();
    if (!currentUser) {
        try {
            const data = await fetchJSON(`${API_BASE}/auth/current`);
            if (data.data) {
                setUserInfo(data.data);
                currentUser = data.data;
            } else {
                // 如果接口返回无数据，设置默认用户
                const defaultUser = { username: "用户", role: "user" };
                setUserInfo(defaultUser);
                currentUser = defaultUser;
            }
        } catch {
            // 如果请求失败，设置默认用户
            const defaultUser = { username: "用户", role: "user" };
            setUserInfo(defaultUser);
            currentUser = defaultUser;
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

// ==================== 任务列表 ====================
async function renderJobList() {
    const jobList = document.getElementById("job-list");
    if (!jobList) return;

    try {
        const data = await fetchJSON(`${API_BASE}/jobs`);
        const jobs = data.jobs || [];

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

// ==================== 任务详情 ====================
let detailTimer = null;

async function renderJobDetail(jobId) {
    clearTimeout(detailTimer);
    const detailSection = document.getElementById("detail-section");
    const detailContent = document.getElementById("detail-content");

    if (!detailSection || !detailContent) return;

    detailSection.style.display = "block";
    detailContent.innerHTML = '<p class="loading-text">正在读取任务详情...</p>';

    try {
        const result = await fetchJSON(`${API_BASE}/jobs/${jobId}`);
        const job = result.job;

        if (!job) {
            detailContent.innerHTML = '<p class="error-text">任务数据为空</p>';
            return;
        }

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
        } else if (job.status === "completed") {
            const reportData = await fetchJSON(`${API_BASE}/jobs/${jobId}/report`);
            const report = reportData.report;

            if (report) {
                const video = report.video || {};
                html += `<h3>📊 分析概览</h3>`;
                html += `<div class="report-grid">
                    <div><strong>视频时长</strong><br>${video.duration || 0} 秒</div>
                    <div><strong>帧率</strong><br>${video.fps || 0} FPS</div>
                    <div><strong>总帧数</strong><br>${video.total_frames || 0}</div>
                    <div><strong>采样帧</strong><br>${video.sampled_frames || 0}</div>
                </div>`;

                if (job.video_clip) {
                    html += `
                        <div class="video-clip-section" style="margin-top:20px; padding:16px; background:#0b0e14; border-radius:8px;">
                            <h3 style="color:#e8edf2; margin-bottom:12px;">🎬 精彩集锦视频</h3>
                            <video controls style="width:100%; max-height:400px; border-radius:6px; background:#000;">
                                <source src="/api/jobs/${jobId}/preview_clip" type="video/mp4">
                                您的浏览器不支持视频播放
                            </video>
                            <a href="/api/jobs/${jobId}/download_clip" download="${jobId}_highlight.mp4" style="display:inline-block; margin-top:10px; padding:8px 16px; background:#2a6b9c; color:white; border-radius:6px; text-decoration:none; font-weight:600;">
                                📥 下载视频
                            </a>
                        </div>
                    `;
                }

                const keyframes = report.keyframes || [];
                if (keyframes.length) {
                    html += `<h3>🖼️ 推荐精彩片段</h3><div class="keyframes-grid" data-job-id="${escapeHtml(jobId)}">`;
                    keyframes.forEach((frame) => {
                        const reviewStatus = frame.review || "pending";
                        const statusText = reviewStatus === "pass" ? "通过" : reviewStatus === "review" ? "待复核" : reviewStatus === "reject" ? "不通过" : "待审核";
                        const statusClass = reviewStatus === "pass" ? "status-pass" : reviewStatus === "review" ? "status-review" : reviewStatus === "reject" ? "status-reject" : "status-pending";
                        html += `
                            <article class="keyframe-card" data-keyframe-id="${escapeHtml(frame.id)}" data-timestamp="${frame.timestamp || 0}">
                                ${frame.image_url ? `<img src="${escapeHtml(frame.image_url)}" alt="片段证据帧" loading="lazy">` : ""}
                                <div class="score">评分 ${Number(frame.score || 0).toFixed(3)}</div>
                                <div class="time">${frame.timestamp || 0} 秒</div>
                                <p>${escapeHtml(frame.label || "画面变化")}</p>
                                <div class="review-status ${statusClass}">${statusText}</div>
                                <div class="actions">
                                    <button class="btn-pass ${reviewStatus === 'pass' ? 'active' : ''}" type="button" data-action="pass">✓ 通过</button>
                                    <button class="btn-review ${reviewStatus === 'review' ? 'active' : ''}" type="button" data-action="review">○ 待复核</button>
                                    <button class="btn-reject ${reviewStatus === 'reject' ? 'active' : ''}" type="button" data-action="reject">✗ 不通过</button>
                                </div>
                            </article>
                        `;
                    });
                    html += `</div>`;
                }

                html += `<p class="loading-text">${escapeHtml(report.message || "分析完成")}</p>`;
            } else {
                html += `<p class="loading-text">暂无分析报告</p>`;
            }
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

// ==================== 主应用初始化 ====================
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
                const result = await fetchJSON(`${API_BASE}/jobs`, { method: "POST", body: formData });
                const job = result.job || result;
                if (!job || !job.job_id) {
                    throw new Error("任务创建失败，响应数据:" + JSON.stringify(result));
                }

                await fetchJSON(`${API_BASE}/jobs/${job.job_id}/analyze`, { method: "POST" });
                fileInput.value = "";
                await renderJobList();
                renderJobDetail(job.job_id);
            } catch (error) {
                console.error("创建任务错误:", error);
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

// ==================== 数据看板（visualization）====================
async function initVisualization() {
    const classDistChartEl = document.getElementById("class-dist-chart");
    const confidenceChartEl = document.getElementById("confidence-chart");
    const videoTimeChartEl = document.getElementById("video-time-chart");
    const taskSelect = document.getElementById("video-task-select");

    // 加载任务列表到下拉框
    if (taskSelect) {
        try {
            const data = await fetchJSON(`${API_BASE}/jobs`);
            const jobs = data.jobs || [];
            taskSelect.innerHTML = '<option value="">选择检测任务</option>';
            jobs.forEach(job => {
                const option = document.createElement("option");
                option.value = job.job_id;
                option.textContent = `${job.project_name || "未命名"} (${job.asset_name || "未知"})`;
                taskSelect.appendChild(option);
            });
        } catch (e) {
            console.error("加载任务列表失败:", e);
        }
    }

    // 加载检测类别统计
    try {
        const classData = await fetchJSON(`${API_BASE}/stats/detect-class`);
        renderClassDistChart(classData.classDistribution || []);
    } catch (e) {
        console.error("加载检测类别失败:", e);
    }

    // 加载置信度分布（如果有数据）
    try {
        const classData = await fetchJSON(`${API_BASE}/stats/detect-class`);
        renderConfidenceChart(classData.confidenceDistribution || []);
    } catch (e) {
        console.error("加载置信度分布失败:", e);
    }

    // 加载视频时间段分析
    if (taskSelect) {
        taskSelect.addEventListener("change", async (e) => {
            const taskId = e.target.value;
            if (taskId) {
                try {
                    const timeData = await fetchJSON(`${API_BASE}/stats/video-time?task_id=${taskId}`);
                    renderVideoTimeChart(timeData);
                } catch (err) {
                    console.error("加载视频时间段失败:", err);
                }
            }
        });
        // 默认加载第一个任务
        if (taskSelect.options.length > 1) {
            taskSelect.value = taskSelect.options[1].value;
            taskSelect.dispatchEvent(new Event("change"));
        }
    }
}

function renderClassDistChart(data) {
    const container = document.getElementById("class-dist-chart");
    if (!container || !data || !data.length) {
        if (container) container.innerHTML = '<p class="loading-text">暂无检测类别数据</p>';
        return;
    }
    // 使用简单的柱状图渲染（不依赖 ECharts，直接用 HTML）
    const total = data.reduce((sum, item) => sum + (item.count || 0), 0);
    let html = '<div style="display:flex;flex-direction:column;gap:6px;">';
    data.slice(0, 10).forEach((item) => {
        const percent = total > 0 ? ((item.count / total) * 100).toFixed(1) : 0;
        html += `
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:80px;font-size:13px;color:#8a9aa8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(item.class)}</span>
                <div style="flex:1;height:16px;background:#1a2026;border-radius:8px;overflow:hidden;">
                    <div style="height:100%;width:${percent}%;background:linear-gradient(90deg,#2a6b9c,#4a8aba);border-radius:8px;"></div>
                </div>
                <span style="font-size:13px;color:#e8edf2;min-width:40px;text-align:right;">${item.count}</span>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}

function renderConfidenceChart(data) {
    const container = document.getElementById("confidence-chart");
    if (!container || !data || !data.length) {
        if (container) container.innerHTML = '<p class="loading-text">暂无置信度数据</p>';
        return;
    }
    const total = data.reduce((sum, item) => sum + (item.count || 0), 0);
    let html = '<div style="display:flex;flex-direction:column;gap:6px;">';
    data.slice(0, 10).forEach((item) => {
        const percent = total > 0 ? ((item.count / total) * 100).toFixed(1) : 0;
        html += `
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:70px;font-size:13px;color:#8a9aa8;">${escapeHtml(item.range)}</span>
                <div style="flex:1;height:16px;background:#1a2026;border-radius:8px;overflow:hidden;">
                    <div style="height:100%;width:${percent}%;background:linear-gradient(90deg,#91cc75,#5470c6);border-radius:8px;"></div>
                </div>
                <span style="font-size:13px;color:#e8edf2;min-width:40px;text-align:right;">${item.count}</span>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}

function renderVideoTimeChart(data) {
    const container = document.getElementById("video-time-chart");
    if (!container || !data || !data.timeLabels || !data.timeLabels.length) {
        if (container) container.innerHTML = '<p class="loading-text">暂无视频时间段数据</p>';
        return;
    }
    const labels = data.timeLabels || [];
    const scores = data.excitementScores || [];
    const counts = data.targetCounts || [];
    const maxScore = Math.max(...scores, 0.1);
    const maxCount = Math.max(...counts, 1);

    let html = '<div style="display:flex;flex-direction:column;gap:6px;">';
    labels.slice(0, 15).forEach((label, i) => {
        const scorePercent = ((scores[i] || 0) / maxScore) * 100;
        const countPercent = ((counts[i] || 0) / maxCount) * 100;
        html += `
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="width:50px;font-size:12px;color:#8a9aa8;">${escapeHtml(label)}</span>
                <div style="flex:1;display:flex;gap:4px;align-items:center;">
                    <div style="flex:1;height:12px;background:#1a2026;border-radius:4px;overflow:hidden;">
                        <div style="height:100%;width:${scorePercent}%;background:#5470c6;border-radius:4px;"></div>
                    </div>
                    <div style="flex:1;height:12px;background:#1a2026;border-radius:4px;overflow:hidden;">
                        <div style="height:100%;width:${countPercent}%;background:#91cc75;border-radius:4px;"></div>
                    </div>
                </div>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}

// ==================== 数据统计（stats）====================
async function initStatsPage() {
    try {
        const overview = await fetchJSON(`${API_BASE}/stats/overview`);
        renderOverviewStats(overview);
    } catch (e) {
        console.error("加载概览统计失败:", e);
    }

    try {
        const audit = await fetchJSON(`${API_BASE}/stats/audit-status`);
        renderAuditStats(audit);
    } catch (e) {
        console.error("加载审核统计失败:", e);
    }

    try {
        const detect = await fetchJSON(`${API_BASE}/stats/detect-class`);
        renderDetectClassTable(detect.classDistribution || []);
    } catch (e) {
        console.error("加载检测类别失败:", e);
    }
}

function renderOverviewStats(stats) {
    const total = document.getElementById("total-tasks");
    const completed = document.getElementById("completed-tasks");
    const pending = document.getElementById("pending-tasks");
    const failed = document.getElementById("failed-tasks");

    if (total) total.textContent = stats.totalTasks || 0;
    if (completed) completed.textContent = stats.completedTasks || 0;
    if (pending) pending.textContent = stats.pendingTasks || 0;
    if (failed) failed.textContent = stats.failedTasks || 0;
}

function renderAuditStats(stats) {
    const pass = document.getElementById("audit-pass-count");
    const review = document.getElementById("audit-review-count");
    const reject = document.getElementById("audit-reject-count");

    if (pass) pass.textContent = stats.passCount || 0;
    if (review) review.textContent = stats.reviewCount || 0;
    if (reject) reject.textContent = stats.rejectCount || 0;
}

function renderDetectClassTable(data) {
    const tbody = document.getElementById("detect-class-body");
    if (!tbody) return;
    if (!data || !data.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="loading-text">暂无检测类别数据</td></tr>';
        return;
    }
    const total = data.reduce((sum, item) => sum + (item.count || 0), 0);
    tbody.innerHTML = data.map((item, index) => {
        const percent = total > 0 ? ((item.count / total) * 100).toFixed(1) : 0;
        return `
            <tr>
                <td>${index + 1}</td>
                <td>${escapeHtml(item.class)}</td>
                <td>${item.count || 0}</td>
                <td>${percent}%</td>
            </tr>
        `;
    }).join("");
}

// ==================== 认证检查与初始化 ====================
async function checkAuthAndInit() {
    const authLoading = document.getElementById("auth-loading");
    const mainApp = document.getElementById("main-app");

    if (authLoading) authLoading.style.display = "flex";

    // ========== 🔧 关键修改2：不再跳转登录，始终加载主界面 ==========
    // 即使没有 token，也自动设置一个默认用户信息
    if (!getUserInfo()) {
        const defaultUser = { username: "用户", role: "user" };
        setUserInfo(defaultUser);
        currentUser = defaultUser;
    }

    // 尝试加载用户信息（如果后端接口失败也不影响）
    await loadUserInfo();
    updateUserInfoDisplay();

    if (mainApp) mainApp.style.display = "block";
    if (authLoading) authLoading.style.display = "none";

    // 初始化主应用
    initMainApp();

    // 根据当前页面初始化对应的功能
    const currentPath = window.location.pathname;
    if (currentPath === "/visualization" || currentPath === "/visualization/") {
        setTimeout(initVisualization, 300);
    } else if (currentPath === "/stats" || currentPath === "/stats/") {
        setTimeout(initStatsPage, 300);
    }
}

// ==================== 页面加载初始化 ====================
document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("login-form")) {
        handleLogin();
    } else if (document.getElementById("register-form")) {
        handleRegister();
    } else {
        checkAuthAndInit();
        handleLogout();
        handleNavDropdown();
    }
});