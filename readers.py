"""Read-only data adapters. Large tabular files are paged, never unpickled."""
from dataclasses import dataclass, field
from pathlib import Path
import csv
import json
import wave
import zipfile
import numpy as np
import pandas as pd

IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp', '.gif'}
SIGNAL_EXT = {'.csv', '.tsv', '.txt', '.npy', '.npz', '.mat', '.h5', '.hdf5', '.wav'}
TIME_NAMES = {'time', 'timestamp', 'time_ms', 'time_s', 'timestamp_ms', 'daqtime', 'jstime', 'dtime', 'seconds', 't'}

@dataclass
class SignalData:
    path: Path
    frame: pd.DataFrame
    offset: int = 0
    has_more: bool = False
    total: int | None = None
    sample_rate: float | None = None
    notes: list = field(default_factory=list)
    arrays: list = field(default_factory=list)
    time_column: str | None = None
    time_unit: str = 's'

    @property
    def numeric(self):
        return [str(c) for c in self.frame.select_dtypes(include='number').columns]

def _sniff(path, header='自动', separator='自动'):
    with open(path, 'rb') as f:
        raw = f.read(65536)
    for encoding in ['utf-8-sig', 'gb18030', 'utf-16']:
        try:
            sample = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('无法识别文本编码；请转为 UTF-8 CSV。')
    lines = [x for x in sample.splitlines() if x.strip() and not x.lstrip().startswith('#')]
    if not lines:
        raise ValueError('文件没有可读数据。')
    if separator == '自动':
        try:
            sep = csv.Sniffer().sniff('\n'.join(lines[:20]), delimiters=',;\t|').delimiter
        except csv.Error:
            sep = r'\s+'
    else:
        sep = {',': ',', ';': ';', 'Tab': '\t', '空格': r'\s+'}[separator]
    import re
    tokens = re.split(sep if sep == r'\s+' else re.escape(sep), lines[0])
    def number(s):
        try:
            float(s.strip().strip('"'))
            return True
        except ValueError:
            return False
    has_header = header == '有表头' or (header == '自动' and not all(number(t) for t in tokens))
    return encoding, sep, has_header

def _frame(arr, offset, limit, name='value', channels_first=None):
    arr = np.asarray(arr)
    if arr.dtype.names:
        return pd.DataFrame.from_records(arr[offset:offset + limit + 1])
    arr = np.squeeze(arr)
    if arr.ndim == 0:
        arr = arr.reshape(1)
    if arr.ndim > 2:
        raise ValueError(f'数组形状 {arr.shape} 超过二维。请选择一维/二维波形变量；图片请用图片文件查看。')
    if arr.dtype.kind not in 'biuf':
        raise ValueError('仅支持实数型数组，不执行 object/pickle 内容。')
    if arr.ndim == 1:
        return pd.DataFrame({name: arr[offset:offset + limit + 1]})
    transpose = channels_first if channels_first is not None else arr.shape[0] <= 64 and arr.shape[1] > max(64, arr.shape[0] * 4)
    if transpose:
        arr = arr.T
    return pd.DataFrame(arr[offset:offset + limit + 1], columns=[f'{name}_{i+1}' for i in range(arr.shape[1])])

def read_signal(path, offset=0, limit=200000, key='', header='自动', separator='自动', orientation='自动'):
    path = Path(path)
    if offset < 0 or not 1 <= limit <= 2000000:
        raise ValueError('起始行不能为负；每页行数应为 1–2,000,000。')
    suffix = path.suffix.lower()
    result = SignalData(path, pd.DataFrame(), offset=offset)
    orient = {'自动': None, '行=样本': False, '列=样本': True}[orientation]
    if suffix in {'.csv', '.tsv', '.txt'}:
        encoding, sep, has_header = _sniff(path, header, separator)
        # Iterate chunks: bounded memory and correct handling of comments/quoted lines.
        kwargs = dict(sep=sep, encoding=encoding, comment='#', header=0 if has_header else None, chunksize=min(100000, limit + 1))
        taken, seen, blocks = 0, 0, []
        with pd.read_csv(path, **kwargs) as chunks:
            for chunk in chunks:
                end = seen + len(chunk)
                if end > offset:
                    part = chunk.iloc[max(0, offset - seen):]
                    part = part.iloc[:limit + 1 - taken]
                    blocks.append(part)
                    taken += len(part)
                seen = end
                if taken >= limit + 1:
                    break
        if blocks:
            result.frame = pd.concat(blocks, ignore_index=True)
        else:
            raise ValueError('起始行已超出文件末尾。')
        if not has_header:
            result.frame.columns = [f'channel_{i+1}' for i in range(result.frame.shape[1])]
        result.notes.append(f'编码 {encoding}；分隔符 {repr(sep)}；表头 {has_header}。CSV 分页读取，不把全文件一次装入内存。')
    elif suffix == '.npy':
        arr = np.load(path, mmap_mode='r', allow_pickle=False)
        result.frame = _frame(arr, offset, limit, channels_first=orient)
        result.notes.append(f'原数组形状 {arr.shape}；只读内存映射。')
    elif suffix == '.npz':
        with np.load(path, allow_pickle=False) as f:
            result.arrays = list(f.files)
            if not result.arrays:
                raise ValueError('NPZ 中没有数组。')
            name = key if key in result.arrays else result.arrays[0]
            arr = f[name]
            result.frame = _frame(arr, offset, limit, name, orient)
            result.notes.append(f'变量 {name}，形状 {arr.shape}；NPZ 需解压选中变量到内存。')
    elif suffix in {'.mat', '.h5', '.hdf5'}:
        import h5py
        if h5py.is_hdf5(path):
            with h5py.File(path, 'r') as f:
                candidates = []
                f.visititems(lambda n, o: candidates.append(n) if isinstance(o, h5py.Dataset) and o.ndim in (1, 2) and o.dtype.kind in 'biuf' else None)
                result.arrays = candidates
                if not candidates:
                    raise ValueError('HDF5 中未找到一维/二维实数数组。')
                name = key if key in candidates else candidates[0]
                ds = f[name]
                is_mat = suffix == '.mat'
                transpose = orient if orient is not None else (is_mat or ds.ndim == 2 and ds.shape[0] <= 64 and ds.shape[1] > 64)
                arr = ds[:, offset:offset+limit+1].T if ds.ndim == 2 and transpose else ds[offset:offset+limit+1]
                result.frame = _frame(arr, 0, limit, name, False)
                result.notes.append(f'HDF5 变量 {name}，原形状 {ds.shape}；只读切片。')
        else:
            from scipy.io import whosmat, loadmat
            candidates = [n for n, shape, kind in whosmat(path) if len(shape) <= 2 and kind not in {'cell', 'struct', 'object', 'char'}]
            result.arrays = candidates
            if not candidates:
                raise ValueError('MAT 没有直接可读的数值矩阵；嵌套 struct/cell 请先导出 CSV。')
            name = key if key in candidates else candidates[0]
            arr = loadmat(path, variable_names=[name])[name]
            result.frame = _frame(arr, offset, limit, name, orient)
            result.notes.append(f'MAT 变量 {name}，形状 {arr.shape}；选中变量加载到内存。')
    elif suffix == '.wav':
        with wave.open(str(path), 'rb') as f:
            result.total = f.getnframes()
            result.sample_rate = float(f.getframerate())
            width, channels = f.getsampwidth(), f.getnchannels()
            if width not in (1, 2, 4):
                raise ValueError('WAV 支持 8/16/32-bit 整数 PCM；请转换其他编码。')
            f.setpos(min(offset, result.total))
            arr = np.frombuffer(f.readframes(limit+1), dtype={1:np.uint8, 2:np.int16, 4:np.int32}[width])
            result.frame = _frame(arr.reshape(-1, channels), 0, limit, 'audio', False)
    else:
        raise ValueError('该格式不能作为波形直接读取。支持 CSV/TSV/TXT、NPY/NPZ、数值 MAT/HDF5、PCM WAV。')
    result.frame.columns = [str(c).strip() for c in result.frame.columns]
    result.has_more = len(result.frame) > limit
    result.frame = result.frame.iloc[:limit].reset_index(drop=True)
    if result.frame.empty:
        raise ValueError('当前分页没有数据。')
    for c in result.frame.columns:
        if result.frame[c].dtype.kind not in 'biuf':
            converted = pd.to_numeric(result.frame[c], errors='coerce')
            if converted.notna().sum() >= max(1, len(converted) * .8):
                result.frame[c] = converted
    result.time_column = next((c for c in result.numeric if c.lower() in TIME_NAMES), None)
    if result.time_column:
        name = result.time_column.lower()
        result.time_unit = 'ms' if name.endswith('_ms') or name in {'daqtime', 'jstime'} else 's'
        result.notes.append(f'时间列自动选择 {result.time_column}（{result.time_unit}）；请按数据说明确认单位。')
    if not result.has_more and result.total is None:
        result.total = offset + len(result.frame)
    return result

def time_axis(data, column='', unit='s', sample_rate=1.0):
    if column and column != '按采样率生成':
        values = pd.to_numeric(data.frame[column], errors='coerce').to_numpy(dtype=float)
        return values * {'s': 1., 'ms': .001, 'us': .000001}[unit]
    if sample_rate <= 0:
        raise ValueError('采样率必须大于 0。')
    return (np.arange(len(data.frame)) + data.offset) / sample_rate

def minmax_envelope(x, y, budget=5000):
    """Preserve narrow physiological peaks, unlike uniform decimation."""
    x, y = np.asarray(x), np.asarray(y)
    if len(y) <= budget:
        return x, y
    buckets = np.array_split(np.arange(len(y)), max(1, budget // 2))
    indices = []
    for b in buckets:
        finite = b[np.isfinite(y[b])]
        if len(finite):
            indices.extend(sorted({int(finite[np.argmin(y[finite])]), int(finite[np.argmax(y[finite])])}))
        else:
            indices.append(int(b[0]))
    return x[indices], y[indices]

def case_annotation(path):
    """Only match CASE folder structure; never infer synchrony from names alone."""
    path = Path(path)
    if path.parent.name == 'physiological':
        candidate = path.parent.parent / 'annotations' / path.name
        if candidate.is_file():
            return candidate
    return None

def read_text_preview(path, max_bytes=300000):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            items = z.infolist()
            return f'ZIP 文件：{len(items)} 项\n解压后总大小：{sum(i.file_size for i in items):,} 字节\n\n' + '\n'.join(f'{i.file_size:>12,}  {i.filename}' for i in items[:1500])
    with open(path, 'rb') as f:
        raw = f.read(max_bytes + 1)
    if b'\x00' in raw[:1000]:
        return '二进制文件；请选择受支持的波形或图片格式。不会执行 pickle/PT 文件。'
    for enc in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            text = raw[:max_bytes].decode(enc)
            return text + ('\n\n[预览已截断]' if len(raw) > max_bytes else '')
        except UnicodeError:
            pass
    return '无法解码文本。'
