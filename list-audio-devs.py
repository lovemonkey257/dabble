import pyaudio

p = pyaudio.PyAudio()

print('Available devices:')
for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        name = dev['name'] # .encode('utf-8')
        print("index:", i, name, dev['maxInputChannels'], dev['maxOutputChannels'], dev['defaultSampleRate'])

print('\ndefault input & output device:')
info = p.get_default_input_device_info()
print(f'Index: {info["index"]}\n\tName: {info["name"]} Max Input Channels: {info["maxInputChannels"]} Max Output Channels: {info["maxOutputChannels"]} Sample Rate: {info["defaultSampleRate"]}')
info = p.get_default_output_device_info()
print(f'Index: {info["index"]}\n\tName: {info["name"]} Max Input Channels: {info["maxInputChannels"]} Max Output Channels: {info["maxOutputChannels"]} Sample Rate: {info["defaultSampleRate"]}')

p.terminate()


'''
{'index': 0, 'structVersion': 2, 'name': 'iStore Audio: USB Audio (hw:0,0)', 'hostApi': 0, 'maxInputChannels': 1, 'maxOutputChannels': 0, 'defaultLowInputLatency': 0.007979166666666667, 'defaultLowOutputLatency': -1.0, 'defaultHighInputLatency': 0.032, 'defaultHighOutputLatency': -1.0, 'defaultSampleRate': 48000.0}
'''
