# Songlist-Converter
Script(s) converting online songlists into ones can be read by local players. Now support SaltMusic.
Core script has been uploaded. Detailed documentation will be refined later.

What you need:
- A set of online playlists from QQMusic, etc., for instance, https://c6.y.qq.com/base/fcgi-bin/u?__=LnLhpEqlZE2n .
- A set of music files (.mp3, .wav, .aac, .flac, etc.) corresponding to your online playlists.
- A python environment.

Intall depedencies: 
'''
pip install rapidfuzz
'''

Before launching the script, you need to install dependencies, convert your online playlist into text, and get the files ready. 
Step 0-1. Install the dependencies using
'''
pip install rapidfuzz
''' 
Step 0-2. Create a new folder and place the converter script inside. Let it be named, for instace, 'workdir'.
Step 1. Use GoMusic (link: https://music.unmeta.cn/ ) to convert an online playlist into <song name - singer> format, and copy and save the results in an plain text file (.txt) .
Step 2. Place the plain text files you got in Step 1 into a subfolder of /workdir. Let it be named, for instace, 'Playlists'.
Step 3. Place the music files into another subfolder of /workdir. Let it be named, for instace, 'Library'.
Step 4. Configure the CONFIG variable in the script according to your actual conditions.
Step 5. Launch the script and get the converted playlist in plain text form (.txt)  in the output directory, it could be named '椒盐歌单_output'. These files will be readable by SaltMusic. 
