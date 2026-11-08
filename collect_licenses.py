"""Bundle installed distribution notices and Python/Tcl/Tk licenses."""
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys

out=Path('build/third-party');out.mkdir(parents=True,exist_ok=True)
index=[]
for dist in distributions():
    name=dist.metadata['Name'];version=dist.version
    index.append(f'{name} {version}')
    for f in dist.files or []:
        if any(k in str(f).lower() for k in ('license','copying','notice')) and Path(dist.locate_file(f)).is_file():
            target=out/name/str(f).replace('../','_').replace('..\\','_')
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(dist.locate_file(f),target)
base=Path(sys.base_prefix)
for f in [base/'LICENSE.txt',base/'LICENSE',*list((base/'tcl').glob('*/license*'))]:
    if f.is_file():
        target=out/'Python'/f.relative_to(base);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,target)
(out/'PACKAGES.txt').write_text('\n'.join(sorted(index)),encoding='utf-8')
