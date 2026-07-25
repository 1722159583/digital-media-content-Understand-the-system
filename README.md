# video-extraction

智能视频精彩片段提取系统的 Flask 后端基线。

## 启动

```powershell
conda activate yolo
python -m pip install -r requirements.txt
python app.py --host 127.0.0.1 --port 7880
```

访问 `http://127.0.0.1:7880/api/health` 确认服务状态。

## 后端职责

- 上传视频、创建任务并保存到 `outputs/<job_id>/input/`；
- 使用后台线程执行分析，不阻塞浏览器上传请求；
- 在 `job.json` 中持久化创建、排队、运行、完成和失败状态；
- 提供任务列表、详情、报告、关键帧人工审核和安全删除接口；
- 通过 `processor.py` 的 `analyze_video(video_path, output_dir, settings)` 接口接入算法模块。未接入时会生成视频元信息报告。

接口约定见 [docs/API.md](docs/API.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m py_compile app.py
```

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
