package com.unisound.vui.engine; public interface ANTPipeline {ANTPipeline fireASREvent(int value); ANTPipeline fireUserEventTriggered(Object value); void playTTS(String text);}
