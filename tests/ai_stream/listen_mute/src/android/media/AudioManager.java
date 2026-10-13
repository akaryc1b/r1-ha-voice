package android.media;
public class AudioManager {
 public static final int STREAM_MUSIC=3;
 public int ownMuteCount,externalMuteCount,musicIndex=2,speechIndex=8,requests,releases;
 public boolean failAcquire,failRelease;
 public void setStreamMute(int stream,boolean mute) {
  if(stream!=3)throw new AssertionError("Only MUSIC may be muted");
  if(mute) {
   if(failAcquire)throw new SecurityException("rejected");
   ownMuteCount++;requests++;
  }else{
   if(failRelease){failRelease=false;throw new IllegalStateException("temporary");}
   if(ownMuteCount<=0)throw new AssertionError("Unbalanced unmute");
   ownMuteCount--;releases++;
  }
 }
 public void setStreamVolume(int stream,int index,int flags){throw new AssertionError("Volume index must never be written");}
 public boolean muted(){return ownMuteCount+externalMuteCount>0;}
 public void reset(){ownMuteCount=externalMuteCount=requests=releases=0;musicIndex=2;speechIndex=8;failAcquire=failRelease=false;}
}
