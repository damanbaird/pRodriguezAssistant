# !/usr/bin/env python3
# -*- coding: utf-8 -*-
# project: pRodriguezAssistant
import subprocess
import time
import threading
import sys
from speech_recognizer import PsLiveRecognizer
from answer_player import AnswerPlayer
from music_player import MusicPlayer
from backlight_control import BacklightControl
from translation_ru import TranslatorRU
import ups_lite

audio_lang = 'en'
recognize_lang ='en'

BacklightControl.backlight_enabled = True
eyes_bl = BacklightControl('EYES')

fsm_state = 1

m_player = MusicPlayer()
a_player = AnswerPlayer(audio_lang)
speech_recognizer = PsLiveRecognizer('./resources/', recognize_lang, 'bender')

QUIET_VOLUME = 8
NORMAL_VOLUME = 20
LOUD_VOLUME = 32
speaker_volume = NORMAL_VOLUME

IDLE_TIME = 60 # in minutes, 2 - minimum
sleep_enabled = True
is_sleeping = False
sleep_counter = 0
sleep_counter_lock = threading.Lock()
main_thread_is_running = True

UPS_TASK_ENABLED = True
UPS_TASK_INTERVAL = 2

VOLUME_STEP = 4

def main():
    global fsm_state
    global m_player
    global speech_recognizer
    global speaker_volume
    global main_thread_is_running

    set_speaker_volume(speaker_volume)

    kill_pocketsphinx()
    m_player.kill_player()

    eyes_bl.exec_cmd('OFF')
    time.sleep(0.15)

    if UPS_TASK_ENABLED:
        ups_thread = threading.Thread(target=ups_task)
        ups_thread.start()

    sleep_thread = threading.Thread(target=sleep_task)
    sleep_thread.daemon = True
    sleep_thread.start()

    sphinx_proc = subprocess.Popen(["%s" % speech_recognizer.cmd_line], shell=True, stdout=subprocess.PIPE)
    print(["%s" % speech_recognizer.cmd_line])

    eyes_bl.exec_cmd('ON')

    while True:
        if (fsm_state == 1):
            if find_keyphrase(sphinx_proc):
                conversation_mode(sphinx_proc)
        elif (fsm_state == 2):
            conversation_mode(sphinx_proc)
        elif (fsm_state == 3):
            break
        elif (fsm_state == 4):
            break
        elif (fsm_state == 5):
            break
        else:
            continue

    main_thread_is_running = False
    kill_pocketsphinx()
    m_player.send_command("exit")

    eyes_bl.exec_cmd('OFF')
    time.sleep(3)
    
    if (fsm_state == 4):
        shutdown()

    if (fsm_state == 5):
        reboot()

    sys.exit(0)

def ups_task():
    global main_thread_is_running
    prev_voltage = ups_lite.read_voltage()
    prev_capacity = ups_lite.read_capacity()
    while main_thread_is_running:
        time.sleep(UPS_TASK_INTERVAL)
        voltage = ups_lite.read_voltage()
        capacity = ups_lite.read_capacity()
        if voltage >= 4.20:
            if prev_voltage <= 4.15:
                a_player.play_answer('electricity')
        else:
            if capacity < 20 and (prev_capacity > capacity):
                shutdown()
        prev_voltage = voltage
        prev_capacity = capacity

def sleep_task():
    global is_sleeping
    global sleep_enabled
    global sleep_counter

    while main_thread_is_running:
        time.sleep(60)
        if sleep_enabled:
            sleep_counter_inc()
            if sleep_counter >= IDLE_TIME:
                if not is_sleeping:
                    m_player.send_command('status')
                    if not m_player.musicIsPlaying:
                        eyes_bl.exec_cmd('OFF')
                        a_player.play_answer('kill all humans')
                        is_sleeping = True

def sleep_counter_inc():
    global sleep_counter
    sleep_counter_lock.acquire()
    sleep_counter += 1
    sleep_counter_lock.release()

def sleep_counter_reset():
    global sleep_counter
    sleep_counter_lock.acquire()
    sleep_counter = 0
    sleep_counter_lock.release()

def wake_up():
    global is_sleeping
    eyes_bl.exec_cmd('ON')
    command = 'wake up'
    a_player.play_answer(command)
    is_sleeping = False

def get_utterance(sphinx_proc):
    retcode = sphinx_proc.returncode
    utt = sphinx_proc.stdout.readline().decode('utf8').rstrip().lower()
    print('utterance = ' + utt)
    return utt

def find_keyphrase(sphinx_proc):
    global fsm_state
    global sleep_enabled
    global is_sleeping
    global aplayer
    global speaker_volume

    while True:
        keyphrase_found = False
        print('Start mode:')

        utt = get_utterance(sphinx_proc)

        if speech_recognizer.lang == 'ru':
            try:
                utt = TranslatorRU.tr_start_ru_en[utt]
            except KeyError as e:
                utt = 'unrecognized'
                #raise ValueError('Undefined key to translate: {}'.format(e.args[0]))

        if ('bender' in utt):
            sleep_counter_reset()
            m_player.send_command('status')
            if m_player.musicIsPlaying:
                if('pause' in utt or speaker_volume == 0):
                    m_player.send_command('pause')
                    keyphrase_found = True
            else:
                if (('hi' in utt) or ('hey' in utt) or ('hello' in utt)) and not is_sleeping:
                    command = 'hey bender'
                    a_player.play_answer(command)
                if is_sleeping:
                    wake_up()
                keyphrase_found = True

        if keyphrase_found:
            return keyphrase_found

def conversation_mode(sphinx_proc):
    global fsm_state
    global sleep_enabled
    global is_sleeping
    global a_player

    while True:
        fsm_state = 1
        print ('Conversation mode:')

        utt = get_utterance(sphinx_proc)

        if speech_recognizer.lang == 'ru':
            try:
                utt = TranslatorRU.tr_conversation_ru_en[utt]
            except KeyError as e:
                utt = 'unrecognized'
                #raise ValueError('Undefined key to translate: {}'.format(e.args[0]))

        if is_sleeping:
            wake_up()
        else:
            command = 'unrecognized'
            if 'shutdown' in utt:
                command = 'shutdown'
                fsm_state = 4
            if 'reboot' in utt:
                command = 'reboot'
                fsm_state = 5
            elif (('exit' in utt) or ('quit' in utt)) and ('program' in utt):
                command = 'exit'
                fsm_state = 3
            elif (utt.endswith('mode')):
                mode_ok = False
                if 'quiet' in utt:
                    set_speaker_volume(QUIET_VOLUME)
                    mode_ok = True
                elif 'normal' in utt:
                    set_speaker_volume(NORMAL_VOLUME)
                    mode_ok = True
                elif 'loud' in utt:
                    set_speaker_volume(LOUD_VOLUME)
                    mode_ok = True
                if mode_ok:
                    command = 'configuration'
            elif ('volume' in utt) or (utt == 'louder') or ('utt' == 'quieter'):
                command = 'configuration'
                if ('increase' in utt or utt == 'louder'):
                    change_speaker_volume(VOLUME_STEP)
                elif ('decrease' in utt or utt == 'quieter'):
                    change_speaker_volume(-VOLUME_STEP)
            elif ('sing' in utt) and ('song' in utt):
                command = 'sing'
            elif 'who are you' in utt:
                command = 'who are you'
            elif 'how are you' in utt:
                command = 'how are you'
            elif ('where are you from' in utt) or ('where were you born' in utt):
                command = 'birthplace'
            elif 'when were you born' in utt:
                command = 'birthdate'
            elif 'your favorite animal' in utt:
                command = 'animal'
            elif 'how can you live' in utt and 'without' in utt and 'body' in utt:
                command = 'body'
            elif 'what do you think about' in utt:
                if 'alexa' in utt or 'alice' in utt or 'cortana' in utt or 'siri' in utt:
                    command = 'bad girl'
            elif 'magnet' in utt:
                command = 'magnet'
            elif 'new sweater' in utt:
                command = 'new sweater'
            elif ('start' in utt and 'player' in utt):
                command = 'player'
                m_player.send_command('start')
                time.sleep(1)
            elif ('stop' in utt and 'player' in utt):
                command = 'player'
                m_player.send_command('stop')
            elif ('next song' in utt):
                command = 'no audio'
                m_player.send_command('next')
            elif ('enable' in utt):
                if ('sleep' in utt):
                    command = 'configuration'
                    sleep_enabled = True
            elif ('disable' in utt):
                if ('sleep' in utt):
                    command = 'configuration'
                    sleep_enabled = False
            elif (utt == 'bender' or ('bender' in utt and ('hi' in utt or 'pause' in utt))):
                command = 'no audio'
                fsm_state = 2

            if fsm_state != 2:
                if command != 'no audio':
                    a_player.play_answer(command)

                if command != 'shutdown' or command != 'reboot':
                    m_player.send_command('status')
                    if m_player.musicIsPlaying:
                        m_player.send_command('resume')
        sleep_counter_reset()

        break

def change_speaker_volume(value):
    global speaker_volume

    speaker_volume += value
    if speaker_volume < 0:
        speaker_volume = 0
    if speaker_volume > 40:
        speaker_volume = 40
    set_speaker_volume(speaker_volume)

def set_speaker_volume(value):
    amixer_exe = "amixer -q -c 1 sset 'Speaker' " + str(value)
    p = subprocess.Popen(["%s" % amixer_exe], shell=True, stdout=subprocess.PIPE)
    code = p.wait()

def kill_pocketsphinx():
    kill_exe = 'killall -s SIGKILL pocketsphinx_co'
    p = subprocess.Popen(["%s" % kill_exe], shell=True, stdout=subprocess.PIPE)
    code = p.wait()

def shutdown():
    shutdown = "shutdown -Ph now"
    p = subprocess.Popen(["%s" % shutdown], shell=True, stdout=subprocess.PIPE)
    code = p.wait()

def reboot():
    reboot = "reboot"
    p = subprocess.Popen(["%s" % reboot], shell=True, stdout=subprocess.PIPE)
    code = p.wait()

main()
