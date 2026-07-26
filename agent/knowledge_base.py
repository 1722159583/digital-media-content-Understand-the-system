"""KnowledgeBase — 知识库模块（Day 2 增强版：30+ 条目 + 向量检索）"""
import json, os, threading
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "knowledge_base.json")
os.makedirs(DATA_DIR, exist_ok=True)


class KnowledgeBase:
    """知识库管理器 — 30+ 条目，支持关键词 + 向量检索"""

    def __init__(self, path: str = KNOWLEDGE_FILE):
        self.path = path; self._lock = threading.Lock()
        self._entries: list[dict] = []; self._embedding_model = None; self._index = None
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f: self._entries = json.load(f)
        else:
            self._entries = self._load_defaults(); self._save()

    def _save(self):
        with self._lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=2)

    def _load_defaults(self) -> list[dict]:
        return [
            # ===== 游戏角色设定 (kb_001-008) =====
            {"id": "kb_001", "category": "角色设定", "title": "战士角色设计规范",
             "content": "战士类角色应具备高力量和高耐力属性，以近战武器为主，定位为团队前排坦克或物理输出。核心设计要素包括武器类型、护甲等级、技能组合和战斗风格。"},
            {"id": "kb_002", "category": "角色设定", "title": "法师角色设计规范",
             "content": "法师类角色以智力为主要属性，擅长远程魔法攻击。应设计多样化的法术系统，包括元素魔法、控制魔法、辅助魔法和范围攻击。"},
            {"id": "kb_003", "category": "角色设定", "title": "刺客角色设计规范",
             "content": "刺客类角色以敏捷为主要属性，擅长近战爆发输出和潜行。核心设计要素包括背刺机制、隐身能力、毒药系统和逃脱技能。"},
            {"id": "kb_004", "category": "角色设定", "title": "角色背景故事编写指南",
             "content": "角色背景故事应包含四个要素：出身环境、人生转折点、核心目标和性格缺陷。好的背景故事能解释角色的动机和行为逻辑，让角色更加立体。"},
            {"id": "kb_005", "category": "角色设定", "title": "NPC 角色设计要素",
             "content": "NPC 角色应具有明确的身份定位和功能作用。任务相关 NPC 需要对话树设计，商店 NPC 需要商品列表，剧情 NPC 需要情感表达。"},
            {"id": "kb_006", "category": "角色设定", "title": "角色属性平衡设计",
             "content": "角色属性应采用点数分配制，确保各职业特色鲜明且平衡。建议使用六维属性：力量、敏捷、智力、耐力、精神、幸运。"},
            {"id": "kb_007", "category": "角色设定", "title": "游戏道具分类标准",
             "content": "游戏道具分为：消耗品（药水、卷轴）、装备（武器、防具、饰品）、材料（矿石、草药）、任务道具（钥匙、信件）、收藏品（纪念品、图鉴）。"},
            {"id": "kb_008", "category": "角色设定", "title": "装备品质等级划分",
             "content": "装备品质从低到高：普通（白色）→ 优秀（绿色）→ 稀有（蓝色）→ 史诗（紫色）→ 传说（橙色）。品质越高基础属性和附加属性越好。"},

            # ===== 游戏关卡设计 (kb_009-016) =====
            {"id": "kb_009", "category": "关卡设计", "title": "关卡难度曲线设计",
             "content": "关卡难度应遵循渐进原则：前10%为教学关，中间60%逐步提升，最后30%达到峰值。每关应包含1-2个难点和适当的休息点，避免玩家疲劳。"},
            {"id": "kb_010", "category": "关卡设计", "title": "任务奖励设计规范",
             "content": "任务奖励应包含经验值、货币和装备三类。普通任务奖励与任务难度匹配，史诗任务奖励应包含稀有物品。奖励数值应控制在不破坏游戏经济系统的范围内。"},
            {"id": "kb_011", "category": "关卡设计", "title": "Boss 战设计原则",
             "content": "Boss 战应包含多阶段战斗机制，每个阶段有新的技能和攻击模式。Boss 应具有明显的弱点可供玩家利用，同时需要团队配合才能击败。"},
            {"id": "kb_012", "category": "关卡设计", "title": "关卡地图设计要点",
             "content": "关卡地图应包含：起点区域、探索区域、战斗区域、隐藏区域和 Boss 区域。地图中应设置存档点、传送点和复活点。"},
            {"id": "kb_013", "category": "关卡设计", "title": "解谜关卡设计思路",
             "content": "解谜关卡应基于场景环境设计，谜题类型包括：推箱子、密码锁、机关触发、环境互动和逻辑推理。谜题提示应在场景中自然融入。"},
            {"id": "kb_014", "category": "关卡设计", "title": "开放世界任务链设计",
             "content": "开放世界任务链应包含主线任务、支线任务、世界事件和随机遭遇。任务之间应有因果关联，玩家的选择会影响后续任务走向和世界状态。"},
            {"id": "kb_015", "category": "关卡设计", "title": "多人副本设计规范",
             "content": "多人副本建议 3-5 人组队，包含小怪清理、精英怪和最终 Boss。副本有时间限制和重置机制，掉落分配可使用队伍分配或个人拾取。"},
            {"id": "kb_016", "category": "关卡设计", "title": "新手引导关卡设计",
             "content": "新手引导关卡应逐步介绍核心玩法：移动→交互→战斗→技能→成长。每个步骤控制在 2-3 分钟内完成，全程有 UI 指引和文字提示。"},

            # ===== 数字媒体素材规范 (kb_017-022) =====
            {"id": "kb_017", "category": "素材规范", "title": "游戏素材分类体系",
             "content": "数字媒体素材按类型分为：角色模型、场景模型、UI素材、特效素材、音效素材、动画素材、剧情动画。每种素材需标注分辨率、格式、大小、用途和版本号。"},
            {"id": "kb_018", "category": "素材规范", "title": "图像素材质量要求",
             "content": "游戏图像素材分辨率不低于 1024x768，关键角色和场景建议 2K 以上。格式优先使用 PNG（透明背景）和 WebP（网页优化）。色彩模式使用 sRGB。"},
            {"id": "kb_019", "category": "素材规范", "title": "3D 模型面数规范",
             "content": "手游角色模型建议 3000-8000 面，端游 10000-30000 面。场景模型按距离使用 LOD 优化。贴图分辨率建议 512x512 到 2048x2048。"},
            {"id": "kb_020", "category": "素材规范", "title": "音频素材技术要求",
             "content": "游戏音效建议使用 WAV 或 OGG 格式，采样率 44100Hz，16bit。背景音乐码率 128-192kbps，音效码率 64-128kbps。"},
            {"id": "kb_021", "category": "素材规范", "title": "视频素材编码标准",
             "content": "游戏宣传视频建议 H.264 编码，分辨率 1920x1080，帧率 30fps，码率 10-15Mbps。支持横屏 16:9 和竖屏 9:16 两种比例。"},
            {"id": "kb_022", "category": "素材规范", "title": "素材命名规范",
             "content": "素材命名格式：项目缩写_类型_名称_版本。例如：GD_Char_Knight_v01。禁止使用中文和特殊字符，使用下划线分隔。"},

            # ===== 内容审核规则 (kb_023-027) =====
            {"id": "kb_023", "category": "审核规则", "title": "游戏内容三级审核标准",
             "content": "审核分为三个等级：通过（pass）表示内容合规可直接发布；待复核（review）表示存在潜在风险需人工确认；不通过（fail）表示存在违规内容需修改。"},
            {"id": "kb_024", "category": "审核规则", "title": "数字媒体合规要求",
             "content": "数字媒体内容须遵守：不得包含违法违规信息、不得侵犯他人知识产权、不得传播虚假信息、游戏内容需符合年龄分级标准、需包含隐私政策和用户协议。"},
            {"id": "kb_025", "category": "审核规则", "title": "游戏年龄分级标准",
             "content": "游戏内容按年龄分级：全年龄（无限制）、12+（轻微暴力）、16+（中度暴力、恐怖）、18+（重度暴力、血腥）。等级越高审核要求越严格。"},
            {"id": "kb_026", "category": "审核规则", "title": "敏感内容处理流程",
             "content": "发现敏感内容后：1.自动标记并拦截 2.通知审核人员 3.人工复核确认 4.记录违规信息 5.根据严重程度执行下架或修改。全程保留操作日志。"},
            {"id": "kb_027", "category": "审核规则", "title": "用户举报处理机制",
             "content": "建立用户举报通道，支持举报不当内容、作弊行为和恶意行为。举报需提供截图和描述，审核团队在 24 小时内响应处理。"},

            # ===== 宣发与运营 (kb_028-033) =====
            {"id": "kb_028", "category": "宣发规范", "title": "游戏宣传素材规范",
             "content": "宣传素材应突出核心卖点和差异化特征。横版素材比例 16:9，竖版 9:16。每套宣传素材应包含：海报、游戏截图、角色立绘和宣传文案。"},
            {"id": "kb_029", "category": "宣发规范", "title": "短视频平台发布要点",
             "content": "短视频平台发布游戏内容建议时长 15-60秒。前3秒必须抓住注意力，中间展示核心玩法，结尾引导互动。添加热门游戏话题标签提高曝光。"},
            {"id": "kb_030", "category": "宣发规范", "title": "游戏社区运营指南",
             "content": "游戏社区应定期发布开发日志、版本更新说明和活动公告。建立玩家反馈渠道，及时回复玩家问题。定期举办社区活动提升活跃度。"},
            {"id": "kb_031", "category": "宣发规范", "title": "游戏测试推广策略",
             "content": "游戏上线前应进行 Alpha 内测、Beta 公测和压力测试。测试阶段通过限量码发放控制用户量，收集反馈优化游戏体验。"},
            {"id": "kb_032", "category": "宣发规范", "title": "数据分析与优化指南",
             "content": "通过埋点收集用户行为数据，分析指标包括：新增用户、留存率、付费率、关卡通过率、在线时长。根据数据持续优化游戏体验和商业化策略。"},
            {"id": "kb_033", "category": "宣发规范", "title": "游戏本地化要求",
             "content": "游戏出海需要进行本地化：文本翻译、UI 适配、支付接入、文化调整、法律合规。优先支持英语、日语、韩语和东南亚语言。"},

            # ===== 检测分析 (kb_034-036) =====
            {"id": "kb_034", "category": "检测分析", "title": "YOLO 检测结果解读",
             "content": "YOLO 检测输出每个目标的类别、置信度和边界框。置信度低于 0.5 的检测结果可能不准确，建议人工复核。同一画面中多个同类目标可能表示群体行为或重复元素。"},
            {"id": "kb_035", "category": "检测分析", "title": "视频关键帧提取策略",
             "content": "视频关键帧提取建议：每 5-10 秒提取一帧，场景切换时强制提取。使用帧差法检测画面变化程度，变化超过阈值时提取关键帧。"},
            {"id": "kb_036", "category": "检测分析", "title": "目标检测常见错误分析",
             "content": "常见检测错误包括：遮挡导致漏检、光照变化影响准确性、小目标难以检测、相似类别混淆。可通过数据增强、多尺度检测和模型集成来改善。"},
        ]

    def list_all(self) -> list[dict]: return list(self._entries)
    def get_by_id(self, entry_id: str) -> Optional[dict]:
        for e in self._entries:
            if e["id"] == entry_id: return e
        return None

    def add_entry(self, category: str, title: str, content: str) -> dict:
        entry = {"id": f"kb_{len(self._entries)+1:03d}", "category": category, "title": title, "content": content}
        self._entries.append(entry); self._save(); return entry

    def delete_entry(self, entry_id: str) -> bool:
        for i, e in enumerate(self._entries):
            if e["id"] == entry_id: self._entries.pop(i); self._save(); return True
        return False

    def search_by_keyword(self, query: str, top_k: int = 5) -> list[dict]:
        if not query: return []
        keywords = query.lower().split()
        scored = []
        for entry in self._entries:
            text = f"{entry['title']} {entry['content']} {entry['category']}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0: scored.append((score, entry))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_k]]

    def _ensure_embedding(self):
        if self._embedding_model is not None: return
        try:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            texts = [f"{e['title']} {e['content']}" for e in self._entries]
            if texts:
                import faiss, numpy as np
                embeddings = self._embedding_model.encode(texts, show_progress_bar=False)
                dim = embeddings.shape[1]
                self._index = faiss.IndexFlatL2(dim)
                self._index.add(np.array(embeddings).astype("float32"))
        except ImportError:
            self._embedding_model = False; self._index = None

    def search_by_vector(self, query: str, top_k: int = 5) -> list[dict]:
        self._ensure_embedding()
        if self._embedding_model is False or self._index is None:
            return self.search_by_keyword(query, top_k)
        try:
            import numpy as np
            query_vec = self._embedding_model.encode([query], show_progress_bar=False)
            distances, indices = self._index.search(np.array(query_vec).astype("float32"), min(top_k, len(self._entries)))
            results = []
            for i, idx in enumerate(indices[0]):
                if idx < len(self._entries):
                    entry = dict(self._entries[idx])
                    entry["score"] = float(1.0 / (1.0 + distances[0][i]))
                    results.append(entry)
            return results
        except Exception:
            return self.search_by_keyword(query, top_k)

    def search(self, query: str, top_k: int = 5, method: str = "hybrid") -> list[dict]:
        if method == "vector": return self.search_by_vector(query, top_k)
        elif method == "hybrid":
            kw = self.search_by_keyword(query, top_k * 2)
            vec = self.search_by_vector(query, top_k * 2)
            seen = set(); merged = []
            for r in kw + vec:
                if r["id"] not in seen: seen.add(r["id"]); merged.append(r)
            return merged[:top_k]
        return self.search_by_keyword(query, top_k)

    def count(self) -> int: return len(self._entries)
    def get_categories(self) -> list[str]:
        return list(set(e["category"] for e in self._entries))
