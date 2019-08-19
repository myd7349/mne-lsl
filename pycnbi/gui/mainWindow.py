#!/usr/bin/env python
#coding:utf-8

"""
  Author:  Arnaud Desvachez --<arnaud.desvachez@gmail.com>
  Purpose: Defines the mainWindow class for the PyCNBI GUI.
  Created: 2/22/2019
"""

import os
import sys
import time
import inspect
import logging
import multiprocessing as mp
from datetime import datetime
from glob import glob
from pathlib import Path
from importlib import import_module, reload

from PyQt5.QtGui import QTextCursor, QFont
from PyQt5.QtCore import pyqtSlot, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog, QFormLayout, QWidget, \
     QFrame, QErrorMessage

from ui_mainwindow import Ui_MainWindow
from streams import MyReceiver, redirect_stdout_to_queue, GuiTerminal, search_lsl_streams_thread
from readWriteFile import read_params_from_file, save_params_to_file
from pickedChannelsDialog import Channel_Select
from connectClass import PathFolderFinder, PathFileFinder, Connect_Directions, Connect_ComboBox, \
     Connect_LineEdit, Connect_SpinBox, Connect_DoubleSpinBox, Connect_Modifiable_List, \
     Connect_Modifiable_Dict,  Connect_Directions_Online, Connect_Bias, Connect_NewSubject

from pycnbi import logger, init_logger
from pycnbi.utils import q_common as qc
from pycnbi.utils import pycnbi_utils as pu
from pycnbi.triggers.trigger_def import trigger_def
import pycnbi.stream_viewer.stream_viewer as viewer
import pycnbi.stream_recorder.stream_recorder as recorder

class cfg_class:
    def __init__(self, cfg):
        for key in dir(cfg):
            if key[0] == '_':
                continue
            setattr(self, key, getattr(cfg, key))

########################################################################
class MainWindow(QMainWindow):
    """
    Defines the mainWindow class for the PyCNBI GUI.
    """
    
    hide_recordTerminal = pyqtSignal(bool)
    signal_error = pyqtSignal(str)
    
    #----------------------------------------------------------------------
    def __init__(self):
        """
        Constructor.
        """
        super(MainWindow, self).__init__()

        self.cfg_struct = None      # loaded module containing all param possible values
        self.cfg_subject = None     # loaded module containing subject specific values
        self.paramsWidgets = {}     # dict of all the created parameters widgets

        self.load_ui_from_file()

        self.redirect_stdout()

        self.connect_signals_to_slots()


        # Define in which modality we are
        self.modality = None
        
        # Recording process
        self.record_terminal = None
        self.recordLogger = logging.getLogger('recorder')
        self.recordLogger.propagate = False
        init_logger(self.recordLogger)        
        
        # To display errors
        self.error_dialog = QErrorMessage(self)
        
        # Mp sharing variables
        self.record_state = mp.Value('i', 0)
        self.protocol_state = mp.Value('i', 0)
        self.lsl_state = mp.Value('i', 0)
        

    # ----------------------------------------------------------------------
    def redirect_stdout(self):
        """
        Create Queue and redirect sys.stdout to this queue.
        Create thread that will listen on the other end of the queue, and send the text to the textedit_terminal.
        """
        queue = mp.Queue()

        self.thread = QThread()

        self.my_receiver = MyReceiver(queue)
        self.my_receiver.mysignal.connect(self.on_terminal_append)
        self.my_receiver.moveToThread(self.thread)

        self.thread.started.connect(self.my_receiver.run)
        self.thread.start()

        redirect_stdout_to_queue(logger, self.my_receiver.queue, 'INFO')


    #----------------------------------------------------------------------
    def load_ui_from_file(self):
        """
        Loads the UI interface from file.
        """
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        
        # Protocol terminal
        self.ui.textEdit_terminal.setReadOnly(1)
        font = QFont()
        font.setPointSize(10)
        self.ui.textEdit_terminal.setFont(font)


    #----------------------------------------------------------------------
    def clear_params(self):
        """
        Clear all previously loaded params widgets.
        """

        if self.ui.scrollAreaWidgetContents_Basics.layout() != None:
            QWidget().setLayout(self.ui.scrollAreaWidgetContents_Adv.layout())
            QWidget().setLayout(self.ui.scrollAreaWidgetContents_Basics.layout())


    # ----------------------------------------------------------------------
    def extract_value_from_module(self, key, values):
        """
        Extracts the subject's specific value associated with key.
        key = parameter name.
        values = list of all the parameters values.
        """
        for v in values:
            if v[0] == key:
                return v[1]

    ## ----------------------------------------------------------------------
    #def read_params_from_file(self, txtFile):
        #"""
        #Loads the parameters from a txt file.
        #"""
        #folderPath = Path(self.ui.lineEdit_pathSearch.text())
        #file = open(folderPath / txtFile)
        #params = file.read().splitlines()
        #file.close()

        #return params

    # ----------------------------------------------------------------------
    def disp_params(self, cfg_template_module, cfg_module):
        """
        Displays the parameters in the corresponding UI scrollArea.
        cfg = config module
        """

        self.clear_params()
        # Extract the parameters and their possible values from the template modules.
        params = inspect.getmembers(cfg_template_module)

        # Extract the chosen values from the subject's specific module.
        all_chosen_values = inspect.getmembers(cfg_module)

        filePath = self.ui.lineEdit_pathSearch.text()

        # Load channels
        if self.modality == 'trainer':
            subjectDataPath = Path('%s/%s/fif' % (os.environ['PYCNBI_DATA'], filePath.split('/')[-1]))
            self.channels = read_params_from_file(subjectDataPath, 'channelsList.txt')    
                
        self.directions = ()

        # Iterates over the classes
        for par in range(2):
            param = inspect.getmembers(params[par][1])
            # Create layouts
            layout = QFormLayout()

            # Iterates over the list
            for p in param:
                # Remove useless attributes
                if '__' in p[0]:
                    continue

                # Iterates over the dict
                for key, values in p[1].items():
                    chosen_value = self.extract_value_from_module(key, all_chosen_values)
                    
                    # For the feedback directions [offline and online].
                    if 'DIRECTIONS' in key:
                        self.directions = values

                        if self.modality is 'offline':
                            nb_directions = 4
                            directions = Connect_Directions(key, chosen_value, values, nb_directions)

                        elif self.modality is 'online':
                            cls_path = self.paramsWidgets['DECODER_FILE'].lineEdit_pathSearch.text()
                            cls = qc.load_obj(cls_path)
                            events = cls['cls'].classes_        # Finds the events on which the decoder has been trained on
                            events = list(map(int, events))
                            nb_directions = len(events)
                            chosen_events = [event[1] for event in chosen_value]
                            chosen_value = [val[0] for val in chosen_value]

                            # Need tdef to convert int to str trigger values
                            try:
                                [tdef.by_value(i) for i in events]
                            except:
                                trigger_file = self.extract_value_from_module('TRIGGER_FILE', all_chosen_values)
                                tdef = trigger_def(trigger_file)
                                # self.on_guichanges('tdef', tdef)
                                events = [tdef.by_value[i] for i in events]

                            directions = Connect_Directions_Online(key, chosen_value, values, nb_directions, chosen_events, events)

                        directions.signal_paramChanged[str, list].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: directions})
                        layout.addRow(key, directions.l)


                    # For providing a folder path.
                    elif 'PATH' in key:
                        pathfolderfinder = PathFolderFinder(key, os.environ['PYCNBI_ROOT'], chosen_value)
                        pathfolderfinder.signal_pathChanged[str, str].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: pathfolderfinder})
                        layout.addRow(key, pathfolderfinder.layout)
                        continue

                    # For providing a file path.
                    elif 'FILE' in key:
                        pathfilefinder = PathFileFinder(key, chosen_value)
                        pathfilefinder.signal_pathChanged[str, str].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: pathfilefinder})
                        layout.addRow(key, pathfilefinder.layout)
                        continue

                    # For the special case of choosing the trigger classes to train on
                    elif 'TRIGGER_DEF' in key:
                        trigger_file = self.extract_value_from_module('TRIGGER_FILE', all_chosen_values)
                        tdef = trigger_def(trigger_file)
                        # self.on_guichanges('tdef', tdef)
                        nb_directions = 4
                        #  Convert 'None' to real None (real None is removed when selected in the GUI)
                        tdef_values = [ None if i == 'None' else i for i in list(tdef.by_name) ]
                        directions = Connect_Directions(key, chosen_value, tdef_values, nb_directions)
                        directions.signal_paramChanged[str, list].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: directions})
                        layout.addRow(key, directions.l)
                        continue

                    # To select specific electrodes
                    elif '_CHANNELS' in key or 'CHANNELS_' in key:
                        ch_select = Channel_Select(key, self.channels, chosen_value)
                        ch_select.signal_paramChanged[str, list].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: ch_select})
                        layout.addRow(key, ch_select.layout)

                    elif 'BIAS' in key:
                        #  Add None to the list in case of no bias wanted
                        self.directions = tuple([None] + list(self.directions))
                        bias = Connect_Bias(key, self.directions, chosen_value)
                        bias.signal_paramChanged[str, object].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: bias})
                        layout.addRow(key, bias.l)

                    # For all the int values.
                    elif values is int:
                        spinBox = Connect_SpinBox(key, chosen_value)
                        spinBox.signal_paramChanged[str, int].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: spinBox})
                        layout.addRow(key, spinBox.w)
                        continue

                    # For all the float values.
                    elif values is float:
                        doublespinBox = Connect_DoubleSpinBox(key, chosen_value)
                        doublespinBox.signal_paramChanged[str, float].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: doublespinBox})
                        layout.addRow(key, doublespinBox.w)
                        continue

                    # For parameters with multiple non-fixed values in a list (user can modify them)
                    elif values is list:
                        modifiable_list = Connect_Modifiable_List(key, chosen_value)
                        modifiable_list.signal_paramChanged[str, list].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: modifiable_list})
                        layout.addRow(key, modifiable_list.frame)
                        continue

                    #  For parameters containing a string to modify
                    elif values is str:
                        lineEdit = Connect_LineEdit(key, chosen_value)
                        lineEdit.signal_paramChanged[str, str].connect(self.on_guichanges)
                        lineEdit.signal_paramChanged[str, type(None)].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: lineEdit})
                        layout.addRow(key, lineEdit.w)
                        continue

                    # For parameters with multiple fixed values.
                    elif type(values) is tuple:
                        comboParams = Connect_ComboBox(key, chosen_value, values)
                        comboParams.signal_paramChanged[str, object].connect(self.on_guichanges)
                        comboParams.signal_additionalParamChanged[str, dict].connect(self.on_guichanges)
                        self.paramsWidgets.update({key: comboParams})
                        layout.addRow(key, comboParams.layout)
                        continue

                    # For parameters with multiple non-fixed values in a dict (user can modify them)
                    elif type(values) is dict:
                        try:
                            selection = chosen_value['selected']
                            comboParams = Connect_ComboBox(key, chosen_value, values)
                            comboParams.signal_paramChanged[str, object].connect(self.on_guichanges)
                            comboParams.signal_additionalParamChanged[str, dict].connect(self.on_guichanges)
                            self.paramsWidgets.update({key: comboParams})
                            layout.addRow(key, comboParams.layout)

                        except:
                            modifiable_dict = Connect_Modifiable_Dict(key, chosen_value, values)
                            modifiable_dict.signal_paramChanged[str, dict].connect(self.on_guichanges)
                            self.paramsWidgets.update({key: modifiable_dict})
                            layout.addRow(key, modifiable_dict.frame)
                        continue

                # Add a horizontal line to separate parameters' type.
                if p != param[-1]:
                    separator = QFrame()
                    separator.setFrameShape(QFrame.HLine)
                    separator.setFrameShadow(QFrame.Sunken)
                    layout.addRow(separator)

                # Display the parameters according to their types.
                if params[par][0] == 'Basic':
                    self.ui.scrollAreaWidgetContents_Basics.setLayout(layout)
                elif params[par][0] == 'Advanced':
                    self.ui.scrollAreaWidgetContents_Adv.setLayout(layout)


    # ----------------------------------------------------------------------
    def load_config(self, cfg_file):
        """
        Dynamic loading of a config file.
        Format the lib to fit the previous developed pycnbi code if subject specific file (not for the templates).
        cfg_path: path to the folder containing the config file.
        cfg_file: config file to load.
        """
        if self.cfg_subject == None or cfg_file[1] not in self.cfg_subject.__file__:
            # Dynamic loading
            sys.path.append(cfg_file[0])
            cfg_module = import_module(cfg_file[1].split('.')[0])
        else:
            cfg_module = reload(self.cfg_subject)

        return cfg_module

    #----------------------------------------------------------------------
    def load_all_params(self, cfg_template, cfg_file):
        """
        Loads the params structure and assign the subject/s specific value.
        It also checks the sanity of the loaded params according to the protocol.
        """
        try:
            # Loads the subject's specific values
            self.cfg_subject = self.load_config(cfg_file)

            # Loads the template
            if self.cfg_struct == None or cfg_template[1] not in self.cfg_struct.__file__:
                self.cfg_struct = self.load_config(cfg_template)

            # Display parameters on the GUI
            self.disp_params(self.cfg_struct, self.cfg_subject)
            
            # Check the parameters integrity
            self.cfg_subject = self.m.check_config(self.cfg_subject)
        
        except Exception as e:
            self.signal_error[str].emit(str(e))


    @pyqtSlot(str, str)
    @pyqtSlot(str, bool)
    @pyqtSlot(str, list)
    @pyqtSlot(str, float)
    @pyqtSlot(str, int)
    @pyqtSlot(str, dict)
    @pyqtSlot(str, tuple)
    @pyqtSlot(str, type(None))
    # ----------------------------------------------------------------------
    def on_guichanges(self, name, new_Value):
        """
        Apply the modification to the corresponding param of the cfg module

        name = parameter name
        new_value = new str value to to change in the module
        """

        # In case of a dict containing several option (contains 'selected')
        try:
            tmp = getattr(self.cfg_subject, name)
            tmp['selected'] = new_Value['selected']
            tmp[new_Value['selected']] = new_Value[new_Value['selected']]
            setattr(self.cfg_subject, name, tmp)
        # In case of simple data format
        except:
            setattr(self.cfg_subject, name, new_Value)

        print("The parameter %s is %s" % (name, getattr(self.cfg_subject, name)))
        print("It's type is: %s \n" % type(getattr(self.cfg_subject, name)))


    # ----------------------------------------------------------------------
    @pyqtSlot()
    def on_click_pathSearch(self):
        """
        Opens the File dialog window when the search button is pressed.
        """
        path_name = QFileDialog.getExistingDirectory(caption="Choose the subject's directory", directory=os.environ['PYCNBI_SCRIPTS'])
        self.ui.lineEdit_pathSearch.clear()
        self.ui.lineEdit_pathSearch.insert(path_name)

    # ----------------------------------------------------------------------
    def look_for_subject_file(self, modality):
        '''
        Look if the subject config file is contained in the subject folder
        
        modality = offline, trainer or online
        '''
        is_found = False
        cfg_file = None
        cfg_path = Path(self.ui.lineEdit_pathSearch.text())
        
        for f in glob(os.fspath(cfg_path / "*.py") , recursive=False):
            fileName =  os.path.split(f)[-1]
            if modality in fileName and 'structure' not in fileName:
                is_found = True
                cfg_file = f
                break
        return is_found, cfg_file    

    #----------------------------------------------------------------------
    def find_structure_file(self, cfg_file, modality):
        """
        Find the structure config file associated with the subject config file
        
        cfg_file: subject specific config file
        modality = offline, trainer or online
        """
        # Find the config template
        tmp = cfg_file.split('.')[0]  # Remove the .py
        tmp = tmp.split('-')[-1]    # Extract the protocol name
        template_path = Path(os.environ['PYCNBI_ROOT']) / 'pycnbi' / 'config_files' / tmp / 'structure_files'
        
        for f in glob(os.fspath(template_path / "*.py") , recursive=False):
            fileName =  os.path.split(f)[-1]
            if modality in fileName and 'structure' in fileName:
                return f            
    
    #----------------------------------------------------------------------
    def prepare_config_files(self, modality):
        """
        Find both the subject config file and the associated structure config
        file paths
        """
        is_found, cfg_file = self.look_for_subject_file(modality)
            
        if is_found is False:
            self.error_dialog.showMessage('Config file missing: copy an ' + modality + ' config file to the subject folder or create a new subjet')
            return None, None
        else:
            cfg_template = self.find_structure_file(cfg_file, modality)
            cfg_file = os.path.split(cfg_file)
            cfg_template = os.path.split(cfg_template)
            
            return cfg_file, cfg_template
            
    # ----------------------------------------------------------------------
    @pyqtSlot()
    def on_click_offline(self):
        """
        Loads the Offline parameters.
        """
        import pycnbi.protocols.train_mi as m

        self.m = m
        self.modality = 'offline'
        cfg_file, cfg_template = self.prepare_config_files(self.modality)
        
        self.ui.checkBox_Record.setChecked(True)
        self.ui.checkBox_Record.setEnabled(False)
        
        if cfg_file and cfg_template:
            self.load_all_params(cfg_template, cfg_file)            

    # ----------------------------------------------------------------------
    @pyqtSlot()
    def on_click_train(self):
        """
        Loads the Training parameters.
        """
        import pycnbi.decoder.trainer as m

        self.m = m
        self.modality = 'trainer'
        cfg_file, cfg_template = self.prepare_config_files(self.modality)
        
        self.ui.checkBox_Record.setChecked(False)
        self.ui.checkBox_Record.setEnabled(False)
        
        if cfg_file and cfg_template:
            self.load_all_params(cfg_template, cfg_file)

    #----------------------------------------------------------------------
    @pyqtSlot()
    def on_click_online(self):
        """
        Loads the Online parameters.
        """
        import pycnbi.protocols.test_mi as m

        self.m = m
        self.modality = 'online'
        cfg_file, cfg_template = self.prepare_config_files(self.modality)
        
        self.ui.checkBox_Record.setChecked(True)
        self.ui.checkBox_Record.setEnabled(True)
        
        if cfg_file and cfg_template:
            self.load_all_params(cfg_template, cfg_file)


        
    #----------------------------------------------------------------------v
    @pyqtSlot()
    def on_click_start(self):
        """
        Launch the selected protocol. It can be Offline, Train or Online.
        """
        self.record_dir = Path(os.environ['PYCNBI_DATA']) / os.path.split(Path(self.ui.lineEdit_pathSearch.text()))[-1]
        
        ccfg = cfg_class(self.cfg_subject)  #  because a module is not pickable

        # Recording shared variable + recording terminal
        if self.ui.checkBox_Record.isChecked():
            if not self.record_terminal:                
                with self.record_state.get_lock():
                    self.record_state.value = 1
                self.record_terminal = GuiTerminal(self.recordLogger, 'INFO', self.width())
                self.hide_recordTerminal[bool].connect(self.record_terminal.setHidden)
            else:
                self.record_terminal.textEdit.clear()
                self.record_terminal.textEdit.insertPlainText('Waiting for the recording to start...\n')
                self.hide_recordTerminal[bool].emit(False)
            
            amp = self.ui.comboBox_LSL.currentData()
            
            # Protocol shared variable
            with self.protocol_state.get_lock():
                self.protocol_state.value = 2  #  0=stop, 1=start, 2=wait            
            
            processesToLaunch = [('recording', recorder.run_gui, [self.record_state, self.protocol_state, self.record_dir, self.recordLogger, amp['name'], amp['serial'], False, self.record_terminal.my_receiver.queue]), \
                                 ('protocol', self.m.run, [ccfg, self.protocol_state, self.my_receiver.queue])]        
                
        else:
            with self.record_state.get_lock():
                self.record_state.value = 0
                
            # Protocol shared variable
            with self.protocol_state.get_lock():
                self.protocol_state.value = 1  #  0=stop, 1=start, 2=wait
            
            processesToLaunch = [('protocol', self.m.run, [ccfg, self.protocol_state, self.my_receiver.queue])]
                  
        launchedProcess = mp.Process(target=launching_subprocesses, args=processesToLaunch)
        launchedProcess.start()
        logger.info(self.modality + ' protocol starting...')

    #----------------------------------------------------------------------
    @pyqtSlot()
    def on_click_stop(self):
        """
        Stop the protocol process
        """
        with self.protocol_state.get_lock():
            self.protocol_state.value = 0
        time.sleep(2)
        self.ui.textEdit_terminal.clear()
        self.hide_recordTerminal[bool].emit(True)

    #----------------------------------------------------------------------
    @pyqtSlot(str)
    def on_terminal_append(self, text):
        """
        Writes to the QtextEdit_terminal the redirected stdout.
        """
        self.ui.textEdit_terminal.moveCursor(QTextCursor.End)
        self.ui.textEdit_terminal.insertPlainText(text)
    
    @pyqtSlot()
    #----------------------------------------------------------------------
    def on_click_newSubject(self):
        """
        Instance a Connect_NewSubject QDialog class
        """
        qdialog = Connect_NewSubject(self, self.ui.lineEdit_pathSearch)
        qdialog.signal_error[str].connect(self.on_error)
    
    #----------------------------------------------------------------------
    def on_error(self, errorMsg):
        """
        Display the error message into a QErrorMessage
        """
        self.error_dialog.showMessage(errorMsg)
        
    #----------------------------------------------------------------------
    def on_click_save_params_to_file(self):
        """
        Save the params to a config_file
        """
        filePath, fileName = os.path.split(self.cfg_subject.__file__)
        fileName = fileName.split('.')[0]       # Remove the .py
        # subjectProtocol = os.path.split(filePath)[1]    # format: subject-protocol
        
        file = self.cfg_subject.__file__.split('.')[0] + '_' + datetime.now().strftime('%m.%d.%d.%M') + '.py'
        filePath = QFileDialog.getSaveFileName(self, 'Save config file', file, 'python(*.py)')
        
        if filePath[0]:
            save_params_to_file(filePath[0], cfg_class(self.cfg_subject))
        else:
            self.signal_error[str].emit('Provide a correct path and file name to save the config parameters')
    
    @pyqtSlot(list)
    #----------------------------------------------------------------------
    def fill_comboBox_lsl(self, amp_list):
        """
        Fill the comboBox with the available lsl streams
        """
        for amp in amp_list:
            amp_formated = '{} ({})'.format(amp[1], amp[2])
            self.ui.comboBox_LSL.addItem(amp_formated, {'name':amp[1], 'serial':amp[2]})
        self.ui.pushButton_LSL.setText('Start')
    
    #----------------------------------------------------------------------
    def on_click_lsl_button(self):
        """
        Find the available lsl streams and display them in the comboBox_LSL
        """
        if self.lsl_state.value == 1:
            self.lsl_state.value = 0
            self.ui.pushButton_LSL.setText('Start')
        else:
            self.lsl_state.value = 1
            self.ui.pushButton_LSL.setText('Stop')

            self.lsl_thread = search_lsl_streams_thread(self.lsl_state, logger)
            self.lsl_thread.signal_lsl_found[list].connect(self.fill_comboBox_lsl)
            self.lsl_thread.start()
    
    #----------------------------------------------------------------------
    def on_click_start_viewer(self):
        """
        Launch the viewer to check the signals in a seperate process 
        """
        amp = self.ui.comboBox_LSL.currentData()
        self.viewer_state = mp.Value('i', 1)
        viewerprocess = mp.Process(target=instantiate_scope, args=[amp, self.viewer_state, logger, self.my_receiver.queue])
        viewerprocess.start()
    
    #----------------------------------------------------------------------
    def on_click_stopviewer(self):
        """
        Stop the viewer process
        """
        with self.viewer_state.get_lock():
            self.viewer_state.value = 0
        
    #----------------------------------------------------------------------
    def connect_signals_to_slots(self):
        """Connects the signals to the slots"""
        
        # New subject button
        self.ui.pushButton_NewSubject.clicked.connect(self.on_click_newSubject)
        # Search folder button
        self.ui.pushButton_Search.clicked.connect(self.on_click_pathSearch)
        # Offline button
        self.ui.pushButton_Offline.clicked.connect(self.on_click_offline)
        # Train button
        self.ui.pushButton_Train.clicked.connect(self.on_click_train)
        # Online button
        self.ui.pushButton_Online.clicked.connect(self.on_click_online)
        # Start button
        self.ui.pushButton_Start.clicked.connect(self.on_click_start)
        # Stop button
        self.ui.pushButton_Stop.clicked.connect(self.on_click_stop)
        # Save conf file
        self.ui.actionSave_config_file.triggered.connect(self.on_click_save_params_to_file)
        # Error dialog
        self.signal_error[str].connect(self.on_error)
        # Start viewer button
        self.ui.pushButton_StartViewer.clicked.connect(self.on_click_start_viewer)
        # Stop viewer button
        self.ui.pushButton_StopViewer.clicked.connect(self.on_click_stopviewer)
        # LSL button
        self.ui.pushButton_LSL.clicked.connect(self.on_click_lsl_button)

#----------------------------------------------------------------------
def instantiate_scope(amp, state, logger=logger, queue=None):
    logger.info('Connecting to a %s (Serial %s).' % (amp['name'], amp['serial']))
    app = QApplication(sys.argv)
    ex = viewer.Scope(amp['name'], amp['serial'], state, queue)
    sys.exit(app.exec_())

#----------------------------------------------------------------------
def launching_subprocesses(*args):
    """
    Launch subprocesses
    
    processesToLaunch = list of tuple containing the functions to launch
    and their args
    """
    launchedProcesses = dict()
    
    for p in args:
        launchedProcesses[p[0]] = mp.Process(target=p[1], args=p[2])
        launchedProcesses[p[0]].start()
    
    # Wait that the protocol is finished to stop recording
    launchedProcesses['protocol'].join()
    
    recordState = args[0][2][0]     #  Sharing variable
    try:        
        with recordState.get_lock():
            recordState.value = 0
    except:
        pass
        
    
#----------------------------------------------------------------------    
def main():
    #unittest.main()
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
