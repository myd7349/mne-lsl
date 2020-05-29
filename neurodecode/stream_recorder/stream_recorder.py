from __future__ import print_function, division

"""
stream_receiver.py
Acquires signals from LSL server and save into buffer.
Command-line arguments:
  #1: AMP_NAME
  #2: AMP_SERIAL (can be omitted if no serial number available)
  If no argument is supplied, you will be prompted to select one
  from a list of available LSL servers.
Example:
  python stream_recorder.py openvibeSignals
TODO:
- Support HDF output.
- Write simulatenously while receivng data.
- Support multiple amps.
Kyuhwa Lee, 2014
Swiss Federal Institute of Technology Lausanne (EPFL)
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import sys
import time
import multiprocessing as mp

import neurodecode.utils.q_common as qc
import neurodecode.utils.pycnbi_utils as pu

from neurodecode.gui.streams import redirect_stdout_to_queue
from neurodecode.stream_recorder._recorder import _Recorder
from neurodecode import logger
from builtins import input


class StreamRecorder:
    """
    Facade class for recording the signals coming from lsl streams.
    
    Parameters
    ----------
    amp_name : str
            Connect to a server named 'amp_name'. None: no constraint.
    amp_serial : str
        Connect to a server with serial number 'amp_serial'. None: no constraint.
    record_dir : str
        The directory where the data will be saved.
    eeg_only : bool
        If true, ignore non-EEG servers.
    logger : Logger
        The logger where to output info. Default is the NeuroDecode logger.
    queue : mp.Queue
        Can redirect sys.stdout to a queue (e.g. used for GUI).
    state : mp.Value
        Multiprocessing sharing variable to stop the recording from another process
        
    Attributes
    ----------
    
    """
    #----------------------------------------------------------------------
    def __init__(self, amp_name=None, amp_serial=None, record_dir=None, eeg_only=False, logger=logger, queue=None, state=mp.Value('i', 0)):
        
        if record_dir is None:
            raise RuntimeError("No recording directory was provided.")
        
        self.logger = logger
        redirect_stdout_to_queue(self.logger, queue, 'INFO')
            
        self.recorder = _Recorder(amp_name, amp_serial, record_dir, eeg_only, self.logger, state)
    
    #----------------------------------------------------------------------
    def connect(self, amp_name=None, amp_serial=None, eeg_only=False):
        """
        Connect to a stream.
        
        Parameters
        ----------
        amp_name : str
                Connect to a server named 'amp_name'. None: no constraint.
        amp_serial : str
            Connect to a server with serial number 'amp_serial'. None: no constraint.
        eeg_only : bool
            If true, ignore non-EEG servers.
        """
        self.recorder.connect(amp_name, amp_serial, eeg_only)
    
    #----------------------------------------------------------------------
    def record(self, gui=False):
        """
        Start the recording.
        """
        if gui is False and not amp_name:
            amp_name, amp_serial = pu.search_lsl(ignore_markers=True)
            self.recorder.connect(amp_name, amp_serial)
        
        self.proc = mp.Process(target=self.recorder.record, args=[])
        self.proc.start()
    
        if gui is False:
            time.sleep(1) # required on some Python distribution
            input()    
            self.stop(self.proc)
    
    #----------------------------------------------------------------------
    def stop(self):
        """
        Stop the recording.
        """
        with self.recorder.state.get_lock():
            self.recorder.state.value = 0
        
        self.logger.info('(main) Waiting for recorder process to finish.')
        self.proc.join(10)
        if self.proc.is_alive():
            self.logger.error('Recorder process not finishing. Are you running from Spyder?')
            self.logger.error('Dropping into a shell')
            qc.shell()
        sys.stdout.flush()
        self.logger.info('Recording finished.')
    
    #----------------------------------------------------------------------
    def _record_gui(self, protocolState, queue=None):
        """
        Start the recording when launched from the GUI.
        """
        self.record(True)
       
        while not self.recorder.state.value:
            pass
        
        # Launching the protocol (shared variable)
        with protocolState.get_lock():
            protocolState.value = 1
        
        # Continue recording until the shared variable changes to 0.
        while self.recorder.state.value:
            time.sleep(1)
        self.stop()

#----------------------------------------------------------------------
if __name__ == '__main__':
    record_dir = None
    amp_name = None
    amp_serial = None
    if len(sys.argv) > 3:
        amp_serial = sys.argv[3]
    if len(sys.argv) > 2:
        amp_name = sys.argv[2]
    if len(sys.argv) > 1:
        record_dir = sys.argv[1]
    
    recorder = StreamRecorder(amp_name=amp_name, amp_serial=amp_serial, record_dir=record_dir, eeg_only=False, logger=logger, queue=None, state=mp.Value('i',0)) 
    recorder.record()