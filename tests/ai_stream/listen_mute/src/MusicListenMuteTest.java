import android.content.Context;
import android.media.AudioManager;
import r1.local.asr.MusicListenMute;

public final class MusicListenMuteTest {
 static int passed;
 static void check(boolean value){if(!value)throw new AssertionError();}
 static void pass(String name){passed++;System.out.println("PASS "+name);}
 public static void main(String[] args){
  MusicListenMute.acquire(true).close();pass("unavailable context is a no-op");
  MuteAudioManager audio=new MuteAudioManager();MusicListenMute.initialize(new Context(audio));
  MusicListenMute.Lease first=MusicListenMute.acquire(true);
  check(audio.muted()&&audio.ownMuteCount==1);first.close();
  check(!audio.muted()&&audio.musicIndex==2&&audio.speechIndex==8);pass("balanced lease leaves both volume indexes unchanged");

  audio.reset();MusicListenMute.acquire(false).close();
  check(audio.requests==0&&audio.releases==0);pass("disabled setting never issues mute");

  audio.reset();first=MusicListenMute.acquire(true);first.close();first.close();
  check(audio.requests==1&&audio.releases==1);pass("finally and cancellation can release the same lease once");

  audio.reset();audio.ownMuteCount=1;first=MusicListenMute.acquire(true);first.close();
  check(audio.ownMuteCount==1&&audio.muted());pass("pre-existing mute by this AudioManager is preserved");

  audio.reset();audio.externalMuteCount=1;first=MusicListenMute.acquire(true);first.close();
  check(audio.ownMuteCount==0&&audio.externalMuteCount==1&&audio.muted());pass("external original mute is preserved");

  audio.reset();first=MusicListenMute.acquire(true);MusicListenMute.Lease second=MusicListenMute.acquire(true);
  first.close();check(audio.ownMuteCount==1&&audio.muted());first.close();
  check(audio.ownMuteCount==1);second.close();check(!audio.muted());pass("late old-session finally cannot unmute new session");

  audio.reset();audio.musicIndex=0;first=MusicListenMute.acquire(true);first.close();
  check(audio.musicIndex==0);pass("original zero-volume stays zero");

  audio.reset();first=MusicListenMute.acquire(true);audio.musicIndex=5;first.close();
  check(audio.musicIndex==5);pass("explicit volume change during listening is not restored to stale value");

  audio.reset();audio.ownMuteCount=1;audio.failAcquire=true;first=MusicListenMute.acquire(true);first.close();
  check(audio.ownMuteCount==1&&audio.releases==0);pass("rejected acquire cannot remove original mute");

  audio.reset();first=MusicListenMute.acquire(true);audio.failRelease=true;first.close();
  check(audio.ownMuteCount==1);first.close();check(audio.ownMuteCount==0);
  pass("failed release retains lease for later finally retry");

  audio.reset();first=MusicListenMute.acquire(true);
  MuteAudioManager replacement=new MuteAudioManager();MusicListenMute.initialize(new Context(replacement));first.close();
  check(audio.releases==1&&replacement.releases==0);pass("lease always releases through original Binder owner");
  System.out.println(passed+" listen mute tests passed");
 }
}
