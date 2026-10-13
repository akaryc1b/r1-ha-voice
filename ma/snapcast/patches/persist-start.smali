.method public static persistStart(Landroid/content/Context;Landroid/content/Intent;)V
    .registers 7
    const-string v0, "ACTION_START"
    invoke-virtual {p1}, Landroid/content/Intent;->getAction()Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v0
    if-eqz v0, :r1_done
    const-string v0, "EXTRA_PERSIST"
    const/4 v1, 0x0
    invoke-virtual {p1, v0, v1}, Landroid/content/Intent;->getBooleanExtra(Ljava/lang/String;Z)Z
    move-result v0
    if-eqz v0, :r1_done
    const-string v0, "EXTRA_HOST"
    invoke-virtual {p1, v0}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-static {v1}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z
    move-result v0
    if-nez v0, :r1_done
    const-string v0, "EXTRA_PORT"
    const/16 v2, 0x6a8
    invoke-virtual {p1, v0, v2}, Landroid/content/Intent;->getIntExtra(Ljava/lang/String;I)I
    move-result v2
    if-lez v2, :r1_done
    const v0, 0xffff
    if-gt v2, v0, :r1_done
    invoke-static {p0}, Lde/badaix/snapcast/utils/Settings;->getInstance(Landroid/content/Context;)Lde/badaix/snapcast/utils/Settings;
    move-result-object v3
    const-string v0, "host"
    invoke-virtual {v3, v0, v1}, Lde/badaix/snapcast/utils/Settings;->put(Ljava/lang/String;Ljava/lang/String;)Lde/badaix/snapcast/utils/Settings;
    const-string v0, "streamPort"
    invoke-virtual {v3, v0, v2}, Lde/badaix/snapcast/utils/Settings;->put(Ljava/lang/String;I)Lde/badaix/snapcast/utils/Settings;
    const/4 v0, 0x1
    invoke-virtual {v3, v0}, Lde/badaix/snapcast/utils/Settings;->setAutostart(Z)V
    # Only the two compiled official engines may be selected by a start intent.
    const-string v0, "EXTRA_PLAYER"
    invoke-virtual {p1, v0}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    const-string v0, "opensl"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :r1_check_oboe
    const-string v1, "OpenSL"
    goto :r1_save_player
    :r1_check_oboe
    const-string v0, "oboe"
    invoke-virtual {v0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2
    if-eqz v2, :r1_done
    const-string v1, "Oboe"
    :r1_save_player
    const-string v0, "audioEngine"
    invoke-virtual {v3, v0, v1}, Lde/badaix/snapcast/utils/Settings;->put(Ljava/lang/String;Ljava/lang/String;)Lde/badaix/snapcast/utils/Settings;
    :r1_done
    return-void
.end method
