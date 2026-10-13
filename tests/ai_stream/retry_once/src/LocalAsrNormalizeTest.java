public final class LocalAsrNormalizeTest {
    static void same(String text) {
        if (!text.equals(NormalizeUnderTest.normalize(text))) throw new AssertionError(text);
    }
    static void normalized(String text,String expected) {
        if (!expected.equals(NormalizeUnderTest.normalize(text))) throw new AssertionError(text);
    }
    public static void main(String[] args) {
        for(String text:new String[]{"随机播放点音乐","放点音乐","放音乐","播放音乐","播放点音乐",
                "播放一些音乐","放一些音乐","播放国语流行","播放暂停这首歌"}) same(text);
        for(String text:new String[]{"播放播放音乐","放放音乐","播放放音乐","放播放音乐吧"})
            normalized(text,"播放音乐");
        normalized("切换一下手","下一首");normalized("上一守歌","上一首");
        normalized(" 暂停。 ","暂停");
        System.out.println("16 normalization cases passed");
    }
}
