"""真实运行入口验收：启动 Flask 进程并检查 Web、API 与核心推荐。

这不是 pytest 单元测试，而是发布门禁调用的独立进程验收：

    python tests/test_e2e_api.py --province yunnan
    python tests/test_e2e_api.py --province yunnan --expect-data-source example

默认要求推荐使用对应省份数据库。只有显式指定 ``example`` 时，示例库降级
才可通过；这样 example.db 不会静默冒充真实推荐。
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _get_text(url: str, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f'GET {url} 返回 HTTP {resp.status}')
        return resp.read().decode('utf-8')


def _get_json(url: str, timeout: float = 10) -> dict:
    return json.loads(_get_text(url, timeout))


def _post_json(url: str, payload: dict, timeout: float = 120) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f'POST {url} 返回 HTTP {resp.status}')
        return json.loads(resp.read().decode('utf-8'))


def _build_payload(province: str) -> dict:
    answers = {
        'q1_name': '运行入口验收考生',
        'q2_gender': '男',
        'q5_exam_id': 'E2E20260001',
        'q6_phone': '13800138000',
        'q11_chinese_score': '120',
        'q12_math_score': '125',
        'q13_english_score': '110',
        'q14_category': '物理类',
        'q15_subject_combo': '物理+化学+生物',
        'q12_total_score': '580',
        'q13_rank': '15000',
        'q31_stability_preference': '3',
        'q32_stress_tolerance': '能适应中等压力',
        'q41_core_demand': '就业率优先',
        'q51_physics_achievement': '良好',
        'q52_physics_willingness': '有兴趣',
        'q53_chemistry_achievement': '良好',
        'q54_chemistry_willingness': '有兴趣',
        'q65_advantage_1': '数学',
    }
    answers.update({f'bf{i:02d}': '3' for i in range(1, 51)})
    answers.update({f'h{i:02d}': 'A' for i in range(1, 77)})

    efficacy_suffixes = [
        'se_cn1', 'se_cn2', 'se_cn3', 'se_cn4', 'se_cn5',
        'se_mt1', 'se_mt2', 'se_mt3', 'se_mt4', 'se_mt5',
        'se_en1', 'se_en2', 'se_en3', 'se_en4', 'se_en5',
    ]
    for index, suffix in enumerate(efficacy_suffixes, 76):
        answers[f'q{index}_{suffix}'] = '3'

    career_suffixes = [
        'cv_income1', 'cv_income2', 'cv_stability1', 'cv_stability2',
        'cv_achievement1', 'cv_achievement2', 'cv_help1', 'cv_help2',
        'cv_creative1', 'cv_creative2', 'cv_balance1', 'cv_balance2',
        'cv_leadership1', 'cv_leadership2', 'cv_autonomy1', 'cv_autonomy2',
        'cv_location1', 'cv_location2', 'cv_learning1', 'cv_learning2',
    ]
    for index, suffix in enumerate(career_suffixes, 91):
        answers[f'q{index}_{suffix}'] = '3'

    return {
        'province': province,
        'answers': answers,
        'category': '物理类',
        'top_n': 10,
    }


def _wait_until_ready(base_url: str, proc: subprocess.Popen, timeout: float = 40) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'服务在就绪前退出，exit={proc.returncode}')
        try:
            health = _get_json(f'{base_url}/api/health', timeout=2)
            if health.get('status') == 'ok':
                return health
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f'服务 {timeout:.0f} 秒内未就绪: {last_error}')


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _assert_server_stopped(port: int, timeout: float = 5) -> None:
    """端口在等待窗口内不再接受 TCP 连接，才确认服务已经退出。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(('127.0.0.1', port)) != 0:
                return
        time.sleep(0.1)
    raise RuntimeError(
        f'验收结束后端口 {port} 未释放，仍有进程接受 TCP 连接'
    )


def run_runtime_acceptance(province: str, expected_data_source: str) -> dict:
    expected_db = (
        PROJECT_ROOT / 'data' / 'example.db'
        if expected_data_source == 'example'
        else PROJECT_ROOT / 'data' / f'{expected_data_source}_gaokao.db'
    )
    if not expected_db.exists() or expected_db.stat().st_size == 0:
        raise RuntimeError(f'期望数据源不存在或为空: {expected_db}')

    port = _free_port()
    base_url = f'http://127.0.0.1:{port}'
    command = [
        sys.executable,
        '-m',
        'gaokao.api.server',
        '--accept-license',
        '--province',
        province,
        '--host',
        '127.0.0.1',
        '--port',
        str(port),
    ]

    summary = None
    failure = None
    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as server_log:
        proc = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            health = _wait_until_ready(base_url, proc)
            if health.get('license') != 'LicenseRef-OpenGaokao-SAL-1.0':
                raise RuntimeError(f'API 许可证标识不一致：{health.get("license")!r}')

            page = _get_text(f'{base_url}/')
            if '<title>OpenGaokao' not in page or 'js/app.js' not in page:
                raise RuntimeError('Web 首页未包含预期标题或 app.js 入口')
            if 'data-source-code' not in page or 'OpenGaokao SAL 1.0' not in page:
                raise RuntimeError('Web 首页未提供用户可见的对应源码入口')

            result_view = _get_text(f'{base_url}/js/result_view.js')
            banner_markers = (
                'renderDataSourceBanner',
                "dataSource === 'example'",
                '不可用于实际填报',
            )
            if not all(marker in result_view for marker in banner_markers):
                raise RuntimeError('示例数据持久警示未随 Web 入口发布')

            result = _post_json(f'{base_url}/api/recommend', _build_payload(province))
            if result.get('error'):
                raise RuntimeError(f"推荐端点返回错误: {result['error']}")
            actual_source = result.get('data_source')
            if actual_source != expected_data_source:
                raise RuntimeError(
                    f'数据源不符：期望 {expected_data_source}，实际 {actual_source or "未标识"}'
                )
            actual_provenance = result.get('data_provenance')
            if not actual_provenance:
                raise RuntimeError('推荐响应缺少 data_provenance 内容来源标记')
            if actual_source == 'example' and actual_provenance != 'synthetic_example':
                raise RuntimeError(
                    f'示例数据来源标记不符: {actual_provenance}'
                )
            if expected_data_source != 'example' and actual_provenance == 'synthetic_example':
                raise RuntimeError('真实省份验收拒绝 synthetic_example 数据')

            schools = result.get('schools') or []
            summary = result.get('summary') or {}
            summary_total = sum(int(summary.get(key, 0)) for key in ('chong', 'wen', 'bao', 'dian'))
            if not schools or summary_total <= 0:
                raise RuntimeError(
                    f'核心推荐为空：schools={len(schools)}，summary_total={summary_total}'
                )
            if not result.get('pipeline'):
                raise RuntimeError('推荐响应缺少可追溯 pipeline')
            analysis = result.get('analysis') or {}
            if not analysis.get('sections'):
                raise RuntimeError('推荐响应缺少分析章节')

            summary = {
                'command': ' '.join(command),
                'health': health.get('status'),
                'page': 'OpenGaokao + js/app.js',
                'data_source': actual_source,
                'data_provenance': actual_provenance,
                'schools': len(schools),
                'summary_total': summary_total,
                'first_school': schools[0].get('name'),
                'pipeline_steps': len(result['pipeline']),
                'analysis_sections': len(analysis['sections']),
            }
        except Exception as exc:
            failure = exc
        finally:
            _stop_process(proc)

        if failure is not None:
            server_log.flush()
            server_log.seek(0)
            log_tail = '\n'.join(server_log.read().splitlines()[-20:])
            if log_tail:
                raise RuntimeError(f'{failure}\n服务日志末尾:\n{log_tail}') from failure
            raise failure

    _assert_server_stopped(port)
    if summary is None:
        raise RuntimeError('验收未产生结果摘要')
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='OpenGaokao 真实运行入口验收')
    parser.add_argument('--province', default='yunnan', help='启动并请求的省份，默认 yunnan')
    parser.add_argument(
        '--expect-data-source',
        default=None,
        help='期望响应 data_source；默认等于 province，演示验收须显式写 example',
    )
    args = parser.parse_args()
    expected = args.expect_data_source or args.province

    try:
        summary = run_runtime_acceptance(args.province, expected)
    except Exception as exc:
        print(f'❌ 真实运行入口验收失败: {exc}', file=sys.stderr)
        return 1

    print('✅ 真实运行入口验收通过')
    for key, value in summary.items():
        print(f'   {key}: {value}')
    print('   restart_semantics: 服务仅在进程存活期间可用；验收已确认退出后不可访问')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
