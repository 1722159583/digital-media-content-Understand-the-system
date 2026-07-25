**基于YOLO+Agent的智能数字媒体内容理解系统API设计表（课程设计专用）**

**通用前置规范**

**1\. 认证规则**：所有需要登录的接口请求头携带 JWT Token，格式：Authorization: Bearer {token}

**2\. 通用返回体**

json  
{  
"code": 200,  
"msg": "操作描述",  
"data": {},  
"traceId": "uuid日志ID"  
}

**3\. 状态码规范**：400参数错误、401未登录、403权限不足、404资源不存在、413文件超限、500服务异常、503模型服务繁忙

**一、用户权限认证模块API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/auth/register | POST | username、password、role、email | 用户基础信息、userId | 用户账号注册，校验用户名唯一性、密码长度、邮箱格式，区分普通用户/管理员角色 | FastAPI、JWT、MySQL |
| /api/auth/login | POST | username、password | access_token、refresh_token、用户角色、会话有效期 | 用户登录认证，生成双Token，添加登录限流，防止暴力破解 | FastAPI、JWT、MySQL |
| /api/auth/logout | POST | JWT Token（请求头） | 操作成功提示 | 销毁用户登录Token，清空当前会话，实现安全退出 | FastAPI、JWT |
| /api/auth/current | GET | JWT Token（请求头） | 用户id、用户名、角色、创建时间、权限列表 | 获取当前登录用户信息，用于页面权限渲染 | FastAPI、JWT、MySQL |
| /api/auth/refresh | POST | refresh_token | 全新access_token、有效期 | 刷新登录会话，延长用户登录状态，避免频繁登录 | FastAPI、JWT |
| /api/user/list | GET | page、size、keyword（可选） | 用户分页列表、总数、分页参数 | 管理员分页查询系统所有用户信息 | FastAPI、MySQL |
| /api/user/{userId} | PUT | userId、role、账号状态 | 修改后用户信息 | 管理员修改用户角色、启用/禁用用户账号 | FastAPI、MySQL |
| /api/user/{userId} | DELETE | userId | 删除成功提示 | 删除用户，级联清理用户关联的任务、素材数据 | FastAPI、MySQL |

**二、媒体素材上传与管理API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/media/upload | POST | file文件、media_type、remark | mediaId、预览地址、素材元数据（分辨率/时长/大小） | 校验文件格式、大小，保存素材文件，写入数据库，生成唯一素材ID，支持图片/短视频上传 | FastAPI、文件流处理、MySQL |
| /api/media/list | GET | media_type、时间范围、keyword、page、size | 素材分页列表、ID、预览图、上传时间、审核状态、关联任务ID | 多条件分页查询用户上传的所有媒体素材 | FastAPI、MySQL |
| /api/media/{mediaId}/preview | GET | mediaId | 素材二进制流 | 返回原图/原视频流，供前端页面预览渲染 | FastAPI、文件IO |
| /api/media/{mediaId} | DELETE | mediaId | 删除成功提示 | 删除本地素材文件及数据库记录，保留关联检测任务数据用于测试 | FastAPI、MySQL、文件IO |
| ws://ip:port/api/media/live-stream | WebSocket | 实时视频帧数据 | 实时检测框、置信度、目标类别 | 接入摄像头/直播流，实时推送画面帧，完成实时YOLO检测 | WebSocket、YOLO、OpenCV、FastAPI |

**三、YOLO视觉检测任务调度API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/detect/task/create | POST | mediaId、yolo_model_version、conf_threshold、enable_tracking、extract_keyframe | taskId、任务排队状态 | 创建异步视觉检测任务，执行视频解码、关键帧采样、YOLO推理，支持目标跟踪、自定义模型推理 | FastAPI、YOLO、OpenCV、异步任务、MySQL |
| /api/detect/task/{taskId} | GET | taskId | 任务状态、目标检测数据、关键帧路径、运动评分、失败原因 | 查询检测任务进度和完整推理结果，捕获模型异常、文件损坏等错误 | FastAPI、YOLO、MySQL |
| /api/detect/task/{taskId}/draw-image | GET | taskId | 带检测标注框的图片流 | 返回绘制目标框、置信度的可视化结果图，用于前端展示 | OpenCV、YOLO、FastAPI |
| /api/detect/task/compare | POST | mediaId、多组模型参数、阈值参数 | 各模型Precision、Recall、mAP指标数据 | 多模型、多阈值检测结果对比，输出模型精度评估数据 | YOLO、FastAPI、数据计算 |
| /api/detect/task/{taskId}/track | GET | taskId | 各目标ID时序坐标、运动轨迹数据 | 获取视频目标跟踪轨迹数据，支撑前端动态轨迹展示 | YOLO、OpenCV、FastAPI |
| /api/detect/task/list | GET | task状态、时间、mediaId、page、size | 检测任务分页列表、任务详情 | 分页查询所有视觉检测任务，支持多条件筛选 | FastAPI、MySQL |

**四、知识库&向量RAG模块API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/kb/create | POST | 知识库名称、分类、描述 | kbId、知识库基础信息 | 创建媒体审核规范、游戏素材规则类知识库，初始化向量库空间 | FastAPI、Chroma/FAISS、MySQL |
| /api/kb/list | GET | page、size、keyword | 知识库分页列表 | 分页查询所有已创建知识库信息 | FastAPI、MySQL |
| /api/kb/{kbId} | DELETE | kbId | 删除成功提示 | 删除知识库，级联清空向量库内所有关联向量数据 | FastAPI、Chroma/FAISS、MySQL |
| /api/kb/{kbId}/doc/upload | POST | kbId、文档文件（txt/md/pdf） | docId、文本分块数、向量入库状态 | 上传知识库文档，自动分块、Embedding向量化，存入向量数据库 | Embedding、Chroma/FAISS、FastAPI |
| /api/kb/{kbId}/doc/list | GET | kbId、page、size | 文档分页列表、上传时间、向量状态 | 查询指定知识库下的所有文档信息 | FastAPI、MySQL |
| /api/kb/{kbId}/doc/{docId} | DELETE | kbId、docId | 删除成功提示 | 删除文档及对应向量数据，同步更新向量索引 | FastAPI、Chroma/FAISS、MySQL |
| /api/kb/retrieve | POST | kbId、query_text、top_k、score_threshold | 匹配文本块、相似度得分、文档溯源 | 根据视觉检测结果语义检索知识库规范，为Agent生成审核建议提供依据 | RAG、Embedding、Chroma/FAISS、FastAPI |
| /api/kb/{kbId}/rebuild | POST | kbId | 索引重建状态 | 文档更新后刷新向量库索引，保证检索准确性 | Chroma/FAISS、FastAPI |

**五、AI Agent工作流调度API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/agent/run | POST | detectTaskId、kbId、workflow_mode、stream | agentSessionId、SSE流式分析结果 | 启动Agent工作流，串联视觉解析、RAG检索、LLM生成，输出素材摘要、标签、审核结论 | LangChain、DeepSeek LLM、RAG、FastAPI、SSE |
| /api/agent/session/list | GET | page、size、时间、审核状态 | Agent会话分页列表、关联素材/任务信息 | 分页查询所有AI智能分析会话记录 | FastAPI、MySQL |
| /api/agent/session/{sessionId} | GET | sessionId | 原始检测数据、知识库片段、AI输出内容、审核结果 | 查询单条Agent分析完整详情，展示全链路推理过程 | FastAPI、MySQL、LLM |
| /api/agent/session/{sessionId}/audit | PUT | sessionId、人工审核状态、备注、修正标签 | 修正后的审核结果 | 人工复核修正AI审核结论，形成人工迭代优化闭环 | FastAPI、MySQL |
| /api/agent/tool/vision-parse | POST | detectTaskId | 视觉检测数据文本化描述 | 独立调用视觉解析工具，将YOLO检测数据转为自然语言 | YOLO、LLM、FastAPI |
| /api/agent/tool/rag-search | POST | query_text、kbId | 知识库匹配结果 | 独立调用RAG检索工具，单独调试向量检索效果 | RAG、Embedding、FastAPI |
| /api/agent/tool/report-generate | POST | detectTaskId、sessionId | 结构化分析报告文本 | 独立生成素材智能分析报告文本 | LLM、FastAPI |

**六、数据统计与可视化API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/stats/overview | GET | 无   | 素材总数、图文数量、任务成败数、审核状态总数 | 系统全局数据统计，支撑首页数据大盘展示 | FastAPI、MySQL、ECharts |
| /api/stats/detect-class | GET | 无   | 目标类别数量、置信度分布区间数据 | 统计YOLO各类目标检测数量与置信度分布，生成柱状图、直方图数据 | FastAPI、数据分析、ECharts |
| /api/stats/video-time | GET | taskId（可选） | 视频各时间段目标数量时序数据 | 统计视频不同时段目标分布，支撑折线图可视化 | FastAPI、OpenCV、ECharts |
| /api/stats/model-metric | GET | 无   | 各模型mAP、Precision、Recall指标 | 汇总多模型检测精度数据，支撑模型对比可视化 | YOLO、数据分析、Plotly |
| /api/stats/audit-status | GET | 无   | 通过/待复核/驳回素材数量占比 | 统计素材审核状态分布，生成饼图数据 | FastAPI、MySQL、ECharts |

**七、报告导出与文件下载API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/export/task/{taskId}/zip | GET | taskId | 完整分析压缩包二进制流 | 打包导出检测JSON、关键帧截图、AI分析文本，生成完整素材分析包 | FastAPI、文件压缩、IO流 |
| /api/export/report | POST | agentSessionId、导出格式（html/pdf） | 报告文件下载链接/文件流 | 自动生成带图表的标准化分析报告，支持HTML、PDF格式导出 | FastAPI、PDF生成、可视化图表 |
| /api/export/media/csv | GET | 无   | 素材元数据CSV文件流 | 批量导出所有测试素材元数据，用于课程测试数据存档 | FastAPI、Pandas、CSV处理 |

**八、系统日志、异常与测试管理API**

|     |     |     |     |     |     |
| --- | --- | --- | --- | --- | --- |
| 接口路径 | 请求方式 | 请求入参 | 响应出参 | 核心业务功能 | 对应技术栈 |
| /api/log/operation | GET | 时间范围、操作类型、page、size | 用户操作日志分页列表 | 记录并查询用户上传、任务创建、知识库修改等所有操作日志 | FastAPI、日志组件、MySQL |
| /api/log/error | GET | 错误类型、时间、page、size | 异常日志、traceId、报错堆栈信息 | 收集YOLO推理、向量库、LLM调用异常，用于问题排查与迭代优化 | FastAPI、日志组件、异常捕获 |
| /api/test/case/upload | POST | 测试素材文件、预期检测结果 | 测试用例ID、入库状态 | 上传课程设计测试素材与预期结果，构建测试数据集 | FastAPI、MySQL、文件处理 |
| /api/test/case/list | GET | page、size、素材类型 | 测试用例列表、素材信息、预期结果 | 管理查看所有测试样例，满足课程20+图片、3+视频测试要求 | FastAPI、MySQL |
| /api/test/case/run | POST | 测试用例ID列表 | 批量测试报告、成功/失败案例统计 | 批量执行自动化测试，输出案例对比报告，支撑课程测试要求 | FastAPI、自动化测试、YOLO、LLM |

**九、核心业务闭环链路说明**

**完整业务流程**：用户登录授权 → 上传媒体素材 → 创建YOLO视觉检测任务 → 模型推理生成检测数据 → RAG知识库语义检索 → Agent工作流整合数据生成审核结果 → 人工复核修正 → 数据可视化统计展示 → 导出标准化分析报告

**异常覆盖范围**：全覆盖文件异常、模型推理异常、向量库异常、LLM调用异常、权限异常、资源不存在异常，满足课程设计失败流程测试要求。

|（注：部分内容可能由 AI 生成）