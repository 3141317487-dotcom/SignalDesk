"""Functional GUI callbacks with hidden windows and temporary exports."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from app import Viewer, CASE
from readers import read_signal, case_annotation

class ViewerTests(unittest.TestCase):
    def test_case_display_selection_and_exports(self):
        v=Viewer();v.withdraw()
        try:
            p=CASE/'data/interpolated/physiological/sub_1.csv'
            d=read_signal(p,limit=10000);a=read_signal(case_annotation(p))
            v.show_signal((d,a));self.assertEqual(len(v.fig.axes),4)
            v.start.set('1');v.end.set('2')
            x,mask,lo,hi=v.window_data();self.assertEqual(int(mask.sum()),1001)
            with tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp)/'export.csv'
                with patch('app.filedialog.asksaveasfilename',return_value=str(out)):v.export()
                exported=pd.read_csv(out)
                self.assertEqual(len(exported),1001)
                self.assertEqual(exported.columns.tolist(),['viewer_time_seconds','ecg','bvp','rsp'])
                np.testing.assert_allclose(exported.ecg,d.frame.ecg.iloc[1000:2001])
                png=Path(tmp)/'plot.png'
                with patch('app.filedialog.asksaveasfilename',return_value=str(png)):v.save_plot()
                with Image.open(png) as im:self.assertGreater(im.width,500)
            v.stats();self.assertEqual(len(v.table.get_children()),3)
            v.original_image=Image.new('RGB',(80,60),'red');v.image_zoom=1;v.render_image()
            self.assertIsNotNone(v.photo)
        finally:v.destroy()

if __name__=='__main__':unittest.main()
