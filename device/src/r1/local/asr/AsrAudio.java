package r1.local.asr;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

/** 网关显式使用单声道 PCM16；直接连接本地 Sherpa 保持 float32 协议。 */
public final class AsrAudio {
    public static boolean isGateway(String url) throws Exception {
        return "/asr".equals(new URI(url).getPath());
    }

    public static String transportUrl(String url) throws Exception {
        if (!isGateway(url)) return url;
        URI parsed=new URI(url);
        StringBuilder query=new StringBuilder();
        String current=parsed.getRawQuery();
        if (current!=null) for(String part:current.split("&")) {
            String key=part.split("=",2)[0];
            if ("audio_format".equals(URLDecoder.decode(key,"UTF-8"))) continue;
            if (query.length()>0) query.append('&');
            query.append(part);
        }
        if (query.length()>0) query.append('&');
        query.append("audio_format=pcm_s16le");
        int mark=url.indexOf('?');
        return (mark<0?url:url.substring(0,mark))+"?"+query;
    }

    public static byte[] mono(byte[] pcm,int count,int channels) {
        if ((channels!=1 && channels!=2) || count<0 || count>pcm.length || count%(channels*2)!=0)
            throw new IllegalArgumentException("PCM frame alignment invalid");
        if (channels==1) return Arrays.copyOf(pcm,count);
        byte[] result=new byte[count/2];
        for(int source=0,target=0;source<count;source+=4,target+=2) {
            result[target]=pcm[source];result[target+1]=pcm[source+1];
        }
        return result;
    }

    public static byte[] floats(byte[] mono) {
        if (mono.length%2!=0) throw new IllegalArgumentException("PCM16 alignment invalid");
        ByteBuffer result=ByteBuffer.allocate(mono.length*2).order(ByteOrder.LITTLE_ENDIAN);
        for(int at=0;at<mono.length;at+=2) {
            short sample=(short)((mono[at]&255)|(mono[at+1]<<8));
            result.putFloat(sample/32768.0f);
        }
        return result.array();
    }
}
