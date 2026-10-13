package r1.local.asr;

import java.io.*;
import java.net.*;
import org.json.JSONObject;

/** 8080 设置页的 JSON 请求与网关代理，不把密钥放入 URL。 */
public final class VoiceSettingsHttp {
    private VoiceSettingsHttp() {}

    public static JSONObject readJson(Socket socket, BufferedReader reader) throws Exception {
        if (reader == null) throw new IllegalArgumentException("需要 POST JSON 请求");
        socket.setSoTimeout(5000);
        int length = -1, total = 0;
        String host = "", origin = "", type = "";
        String line;
        while ((line = reader.readLine()) != null && line.length() != 0) {
            total += line.length();
            if (total > 16384) throw new IllegalArgumentException("请求头过长");
            int split = line.indexOf(':');
            if (split < 0) continue;
            String name = line.substring(0,split).trim();
            String value = line.substring(split+1).trim();
            if ("Content-Length".equalsIgnoreCase(name)) length = Integer.parseInt(value);
            if ("Content-Type".equalsIgnoreCase(name)) type = value;
            if ("Host".equalsIgnoreCase(name)) host = value;
            if ("Origin".equalsIgnoreCase(name)) origin = value;
        }
        if (length < 0 || length > 32768 || !type.startsWith("application/json"))
            throw new IllegalArgumentException("需要不超过 32 KB 的 JSON 请求");
        if (origin.length() > 0) {
            URI source = new URI(origin);
            if (!("http".equals(source.getScheme()) || "https".equals(source.getScheme())) ||
                    !host.equalsIgnoreCase(source.getRawAuthority()))
                throw new IllegalArgumentException("请从音箱的配置网页保存设置");
        }
        StringBuilder body = new StringBuilder();
        int remaining = length;
        // 原网页使用 BufferedReader；按 UTF-8 字节数计算 Content-Length。
        while (remaining > 0) {
            int value = reader.read();
            if (value < 0) throw new EOFException();
            char ch = (char)value;
            body.append(ch);
            int bytes;
            if (Character.isHighSurrogate(ch)) {
                int next = reader.read();
                if (next < 0 || !Character.isLowSurrogate((char)next))
                    throw new IllegalArgumentException("请求编码无效");
                body.append((char)next); bytes = 4;
            } else {
                bytes = ch <= 0x7f ? 1 : ch <= 0x7ff ? 2 : 3;
            }
            remaining -= bytes;
            if (remaining < 0) throw new IllegalArgumentException("请求长度无效");
        }
        return new JSONObject(body.toString());
    }

    public static JSONObject gateway(String path, JSONObject body) throws Exception {
        String base = CloudVoiceSettings.gatewayUrl(CloudVoiceSettings.read());
        HttpURLConnection connection = (HttpURLConnection)new URL(base+path).openConnection();
        connection.setConnectTimeout(1500);
        connection.setReadTimeout("/asr/test".equals(path) ? 65000 : 10000);
        connection.setRequestProperty("Accept","application/json");
        try {
            if (body != null) {
                byte[] data = body.toString().getBytes("UTF-8");
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
                connection.setFixedLengthStreamingMode(data.length);
                connection.setDoOutput(true);
                OutputStream output = connection.getOutputStream();
                output.write(data); output.close();
            }
            int status = connection.getResponseCode();
            InputStream input = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            if (input == null) throw new IOException("网关未返回配置");
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            try {
                byte[] chunk = new byte[2048]; int count;
                while ((count = input.read(chunk)) != -1) {
                    if (buffer.size()+count > 262144) throw new IOException("网关响应过长");
                    buffer.write(chunk,0,count);
                }
            } finally { input.close(); }
            JSONObject result = new JSONObject(new String(buffer.toByteArray(),"UTF-8"));
            if (status >= 400 && !result.has("error")) result.put("error","网关请求失败");
            return result;
        } finally { connection.disconnect(); }
    }
}
