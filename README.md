# video-extraction

基于 YOLO + OpenCV 的游戏视频五杀检测与精彩片段提取系统。

## 启动

```powershell
conda activate yolo
python -m pip install -r requirements.txt
ffmpeg -version
python app.py --host 127.0.0.1 --port 7880
```

粗剪功能要求系统已安装 FFmpeg 且 `ffmpeg` 位于 `PATH`。访问
`http://127.0.0.1:7880/api/health`，确认 `ffmpeg_available` 为 `true`。

## 后端职责

- 上传视频、创建任务并保存到 `outputs/<job_id>/input/`；
- 使用后台线程执行分析，不阻塞浏览器上传请求；
- 在 `job.json` 中持久化创建、排队、运行、完成和失败状态；
- 提供任务列表、详情、报告、关键帧人工审核和安全删除接口；
- 使用 `train-4` 正式权重检测五杀画面，返回类别、置信度、检测框和时间戳；
- 计算画面变化、运动强度和目标数量得分，生成目标 ID 与轨迹；
- 保存带检测框的关键证据帧，并标记低置信度或无检测结果；
- 使用 FFmpeg 将高光时间段编码为 H.264/AAC，并合并为可预览、可下载的 MP4；
- 解析并持久化 Agent 的摘要、标签、审核建议和额外结构化结果；
- 当前仅支持 `penta_kill`，模型限制及实测结果见 [models/README.md](models/README.md)。

接口约定见 [docs/API.md](docs/API.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py
```

首次加载 PyTorch/Ultralytics 的耗时明显高于后续推理。部署时应在接收业务请求前
调用 `source_code.cv_service.load_model()` 完成模型预热。

## 游戏高光数据采集

安装依赖后，默认采集“LOL 五杀”和“CS GO 五杀”各 15 条元数据，并下载前 5 个高清视频：

```powershell
python crawler/dataset_crawler.py
```

元数据保存到 `data/dataset_metadata.csv`，视频保存到 `data/videos/`。只更新元数据时运行：

```powershell
python crawler/dataset_crawler.py --skip-download
```

可通过 `--keyword "LOL 五杀"` 选择单个关键词；脚本会自动保证总记录数不少于 30。下载数量可通过 `--download-count 5` 至 `--download-count 10` 调整。

## 游戏截图数据采集

默认从百度图片分别采集 60 张 LOL 和 CSGO 高光截图：

```powershell
python data_acquisition/image_crawler.py
```

通过尺寸和图片解码校验的文件保存在 `data_acquisition/raw_images/`，成功记录写入 `data_acquisition/dataset_images_metadata.csv`。脚本可重复运行并从已有有效文件继续采集。

## AnyLabeling 标注与 YOLO 数据集

标注数据集仍保留 `penta_kill`、`multi_kill`、`kill_feed` 三类扩展结构，顺序见
`data_acquisition/classes.txt`。AnyLabeling JSON 保存到
`data_acquisition/annotations/anylabeling/`，导出的训练数据保存到
`data_acquisition/yolo_dataset/`。详细框选规范与操作流程见
`data_acquisition/labeling_guide.md`。

20 张种子图训练与候选自动标注：

```powershell
python data_acquisition/bootstrap_autolabel.py prepare
python data_acquisition/bootstrap_autolabel.py train
python data_acquisition/bootstrap_autolabel.py predict
```

自动生成的 JSON 仅为候选结果，必须按标注指导文档完成人工复核后才能加入训练集。

注意：当前正式 `train-4` 权重仅用于五杀检测，不能将其训练日志指标解释为已经
支持上述三类。恢复三分类前必须修正已有类别编号并补齐独立验证样本。
