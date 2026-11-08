import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.io import savemat
import h5py
from readers import read_signal, time_axis, minmax_envelope, case_annotation

class ReadersTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_csv_page_and_time(self):
        p=self.root/'a.csv';pd.DataFrame({'daqtime':np.arange(20)*50,'ecg':np.arange(20)}).to_csv(p,index=False)
        d=read_signal(p,offset=5,limit=4)
        self.assertEqual(d.frame.ecg.tolist(),[5,6,7,8]);self.assertTrue(d.has_more)
        np.testing.assert_allclose(time_axis(d,'daqtime','ms'),[.25,.3,.35,.4])
        end=read_signal(p,offset=18,limit=4);self.assertFalse(end.has_more);self.assertEqual(end.total,20)
    def test_headerless(self):
        p=self.root/'x.tsv';p.write_text('1\t2\n3\t4\n5\t6\n')
        d=read_signal(p);self.assertEqual(d.frame.shape,(3,2));self.assertEqual(d.frame.iloc[0,0],1)
    def test_multichannel_arrays(self):
        a=np.arange(600).reshape(3,200);p=self.root/'x.npy';np.save(p,a)
        d=read_signal(p,offset=10,limit=20);np.testing.assert_equal(d.frame.to_numpy(),a[:,10:30].T)
        p=self.root/'x.npz';np.savez(p,first=np.arange(100),second=np.arange(200))
        d=read_signal(p,key='second',limit=10);self.assertEqual(len(d.arrays),2);self.assertEqual(d.frame.shape,(10,1))
    def test_mat_hdf5(self):
        a=np.arange(200).reshape(100,2);p=self.root/'x.mat';savemat(p,{'signal':a})
        d=read_signal(p,offset=3,limit=5);np.testing.assert_equal(d.frame.to_numpy(),a[3:8])
        p=self.root/'x.h5'
        with h5py.File(p,'w') as f:f.create_dataset('record/ecg',data=a)
        d=read_signal(p,offset=3,limit=5);np.testing.assert_equal(d.frame.to_numpy(),a[3:8])
    def test_peak_envelope(self):
        x=np.arange(100000);y=np.zeros(100000);y[43219]=99;y[50111]=-40
        px,py=minmax_envelope(x,y,1000)
        self.assertIn(99,py);self.assertIn(-40,py);self.assertLessEqual(len(px),1000);self.assertTrue(np.all(np.diff(px)>0))
    def test_case_pair(self):
        p=self.root/'interpolated/physiological/sub_1.csv';p.parent.mkdir(parents=True);p.touch()
        q=self.root/'interpolated/annotations/sub_1.csv';q.parent.mkdir();q.touch()
        self.assertEqual(case_annotation(p),q)
    def test_no_pickle(self):
        p=self.root/'object.npy';np.save(p,np.array([{'x':1}],dtype=object))
        with self.assertRaises(ValueError):read_signal(p)

if __name__=='__main__':unittest.main()
