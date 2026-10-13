package com.unisound.client; public interface IAudioSource {int openAudioIn(); void closeAudioIn(); int readData(byte[] data,int count);}
