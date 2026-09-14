"""Interface translations.

`t(key, lang, **fields)` returns the string for that key, formatted with the
given fields. Resolution falls back rather than failing: the requested
language, then English, then the key itself. A key that has not been
translated yet therefore degrades to English and never breaks a command — which
is what lets the menus and the most-seen replies be translated first and the
rare technical strings later.

Interface language is a separate setting from search region: `!language` picks
this, `!setregion` picks which country's results YouTube returns.
"""
from __future__ import annotations

import logging

import config

log = logging.getLogger("ytplug.i18n")

# Every string the bot shows often enough to be worth translating. English is
# the reference: any key missing from another language falls back to it.
STRINGS: dict[str, dict[str, str]] = {
    # -- generic ---------------------------------------------------------
    "busy": {
        "en": "⏳ **Busy right now** — a few searches are already running. Try again in a moment.",
        "tr": "⏳ **Şu an yoğunum** — birkaç arama zaten sürüyor. Birazdan tekrar dene.",
        "de": "⏳ **Gerade beschäftigt** — es laufen schon einige Suchen. Versuch es gleich nochmal.",
        "fr": "⏳ **Occupé pour le moment** — des recherches sont déjà en cours. Réessaie dans un instant.",
    },
    "rate_limited": {
        "en": "⚠️ **Rate Limit Exceeded:** <@{user}>, please slow down! Try again in {seconds}s.",
        "tr": "⚠️ **Hız Sınırı Aşıldı:** <@{user}>, biraz yavaşla! {seconds} sn sonra tekrar dene.",
        "de": "⚠️ **Ratenlimit erreicht:** <@{user}>, bitte langsamer! Versuch es in {seconds}s nochmal.",
        "fr": "⚠️ **Limite atteinte :** <@{user}>, doucement ! Réessaie dans {seconds}s.",
    },
    "blocked": {
        "en": "⚠️ **YouTube refused the request:** `{error}`",
        "tr": "⚠️ **YouTube isteği reddetti:** `{error}`",
        "de": "⚠️ **YouTube hat die Anfrage abgelehnt:** `{error}`",
        "fr": "⚠️ **YouTube a refusé la requête :** `{error}`",
    },
    "unexpected": {
        "en": "💥 Something went wrong — it has been logged.",
        "tr": "💥 Bir şeyler ters gitti — kayıtlara yazıldı.",
        "de": "💥 Etwas ist schiefgelaufen — es wurde protokolliert.",
        "fr": "💥 Quelque chose s'est mal passé — c'est enregistré.",
    },
    "guild_only": {
        "en": "❌ That command only works inside a server.",
        "tr": "❌ Bu komut yalnızca bir sunucu içinde çalışır.",
        "de": "❌ Dieser Befehl funktioniert nur auf einem Server.",
        "fr": "❌ Cette commande ne fonctionne que dans un serveur.",
    },
    "owner_only": {
        "en": "🛑 **Error:** Bot owner only.",
        "tr": "🛑 **Hata:** Yalnızca bot sahibi.",
        "de": "🛑 **Fehler:** Nur für den Bot-Besitzer.",
        "fr": "🛑 **Erreur :** Réservé au propriétaire du bot.",
    },
    "denied": {
        "en": "🛑 **Error:** You're not allowed to use this command.",
        "tr": "🛑 **Hata:** Bu komutu kullanma yetkin yok.",
        "de": "🛑 **Fehler:** Du darfst diesen Befehl nicht benutzen.",
        "fr": "🛑 **Erreur :** Tu n'as pas le droit d'utiliser cette commande.",
    },
    "missing_arg": {
        "en": "❌ Missing argument. Usage: `{usage}`",
        "tr": "❌ Eksik argüman. Kullanım: `{usage}`",
        "de": "❌ Fehlendes Argument. Verwendung: `{usage}`",
        "fr": "❌ Argument manquant. Utilisation : `{usage}`",
    },
    "usage": {
        "en": "⚠️ Usage: `{usage}`",
        "tr": "⚠️ Kullanım: `{usage}`",
        "de": "⚠️ Verwendung: `{usage}`",
        "fr": "⚠️ Utilisation : `{usage}`",
    },

    # -- search ----------------------------------------------------------
    "searching": {
        "en": "🔍 Searching YouTube for: `{query}`...",
        "tr": "🔍 YouTube'da aranıyor: `{query}`...",
        "de": "🔍 Suche auf YouTube nach: `{query}`...",
        "fr": "🔍 Recherche sur YouTube : `{query}`...",
    },
    "smart_cache": {
        "en": "⚡ **Smart Cache:** Fast-loading results for `{query}`...",
        "tr": "⚡ **Akıllı Önbellek:** `{query}` sonuçları hızlı yükleniyor...",
        "de": "⚡ **Smart Cache:** Ergebnisse für `{query}` werden schnell geladen...",
        "fr": "⚡ **Cache intelligent :** chargement rapide des résultats pour `{query}`...",
    },
    "no_results": {
        "en": "❌ No videos found for: `{query}`.",
        "tr": "❌ `{query}` için video bulunamadı.",
        "de": "❌ Keine Videos gefunden für: `{query}`.",
        "fr": "❌ Aucune vidéo trouvée pour : `{query}`.",
    },
    "no_live": {
        "en": "📡 No live streams for: `{query}`.",
        "tr": "📡 `{query}` için canlı yayın yok.",
        "de": "📡 Keine Livestreams für: `{query}`.",
        "fr": "📡 Aucun direct pour : `{query}`.",
    },
    "no_search_memory": {
        "en": "❌ No search found in memory. Use `{prefix}s <query>` first.",
        "tr": "❌ Hafızada arama yok. Önce `{prefix}s <sorgu>` kullan.",
        "de": "❌ Keine Suche im Speicher. Nutze zuerst `{prefix}s <Suche>`.",
        "fr": "❌ Aucune recherche en mémoire. Utilise d'abord `{prefix}s <requête>`.",
    },
    "pick_from_page": {
        "en": "❌ Pick a number between 1 and {count} from the current page.",
        "tr": "❌ Bu sayfadan 1 ile {count} arasında bir numara seç.",
        "de": "❌ Wähle eine Zahl zwischen 1 und {count} auf dieser Seite.",
        "fr": "❌ Choisis un numéro entre 1 et {count} sur cette page.",
    },
    "selected": {
        "en": "🔗 **Selected Video ({index}):** {url}",
        "tr": "🔗 **Seçilen Video ({index}):** {url}",
        "de": "🔗 **Ausgewähltes Video ({index}):** {url}",
        "fr": "🔗 **Vidéo sélectionnée ({index}) :** {url}",
    },
    "no_such_page": {
        "en": "❌ There is no page {page} — this search has {pages}.",
        "tr": "❌ {page}. sayfa yok — bu aramada {pages} sayfa var.",
        "de": "❌ Seite {page} gibt es nicht — diese Suche hat {pages}.",
        "fr": "❌ La page {page} n'existe pas — cette recherche en a {pages}.",
    },
    "message_gone": {
        "en": "⚠️ The original result message is gone. Run the search again.",
        "tr": "⚠️ Orijinal sonuç mesajı kaybolmuş. Aramayı tekrar yap.",
        "de": "⚠️ Die ursprüngliche Ergebnisnachricht ist weg. Suche erneut.",
        "fr": "⚠️ Le message de résultats d'origine a disparu. Relance la recherche.",
    },
    "trending_connecting": {
        "en": "🌍 **Connecting to Global Network...** Fetching trending videos.",
        "tr": "🌍 **Küresel Ağa Bağlanılıyor...** Trend videolar getiriliyor.",
        "de": "🌍 **Verbinde mit dem globalen Netzwerk...** Trend-Videos werden geladen.",
        "fr": "🌍 **Connexion au réseau mondial...** Récupération des tendances.",
    },
    "trending_failed": {
        "en": "❌ **Error:** Could not fetch trending data. YouTube might be blocking the request.",
        "tr": "❌ **Hata:** Trend verisi alınamadı. YouTube isteği engelliyor olabilir.",
        "de": "❌ **Fehler:** Trend-Daten konnten nicht geladen werden. YouTube blockiert möglicherweise.",
        "fr": "❌ **Erreur :** impossible de récupérer les tendances. YouTube bloque peut-être la requête.",
    },
    "channel_scanning": {
        "en": "📡 **Scanning Channel (Latest):** `{query}`...",
        "tr": "📡 **Kanal Taranıyor (En Yeni):** `{query}`...",
        "de": "📡 **Kanal wird gescannt (Neueste):** `{query}`...",
        "fr": "📡 **Analyse de la chaîne (récent) :** `{query}`...",
    },
    "channel_not_found": {
        "en": "❌ **Channel or videos not found:** {error}",
        "tr": "❌ **Kanal veya videolar bulunamadı:** {error}",
        "de": "❌ **Kanal oder Videos nicht gefunden:** {error}",
        "fr": "❌ **Chaîne ou vidéos introuvables :** {error}",
    },

    # -- queue -----------------------------------------------------------
    "queue_empty": {
        "en": "📭 Your playlist is empty.",
        "tr": "📭 Kuyruğun boş.",
        "de": "📭 Deine Playlist ist leer.",
        "fr": "📭 Ta playlist est vide.",
    },
    "queue_empty_action": {
        "en": "❌ Your playlist is empty!",
        "tr": "❌ Kuyruğun boş!",
        "de": "❌ Deine Playlist ist leer!",
        "fr": "❌ Ta playlist est vide !",
    },
    "added_one": {
        "en": "✅ **Added to Playlist:** `{title}`\n*(Queue: **{total}**)*",
        "tr": "✅ **Kuyruğa Eklendi:** `{title}`\n*(Kuyruk: **{total}**)*",
        "de": "✅ **Zur Playlist hinzugefügt:** `{title}`\n*(Warteschlange: **{total}**)*",
        "fr": "✅ **Ajouté à la playlist :** `{title}`\n*(File : **{total}**)*",
    },
    "added_many": {
        "en": "✅ **Added {count} tracks to Playlist!** *(Queue: **{total}**)*",
        "tr": "✅ **Kuyruğa {count} parça eklendi!** *(Kuyruk: **{total}**)*",
        "de": "✅ **{count} Titel zur Playlist hinzugefügt!** *(Warteschlange: **{total}**)*",
        "fr": "✅ **{count} morceaux ajoutés !** *(File : **{total}**)*",
    },
    "invalid_numbers": {
        "en": "❌ Please enter valid numbers from the current page.",
        "tr": "❌ Bu sayfadan geçerli numaralar gir.",
        "de": "❌ Bitte gib gültige Zahlen von dieser Seite ein.",
        "fr": "❌ Entre des numéros valides de cette page.",
    },
    "invalid_tracks": {
        "en": "❌ Please enter valid track numbers between 1 and {count}.",
        "tr": "❌ 1 ile {count} arasında geçerli parça numaraları gir.",
        "de": "❌ Bitte gib gültige Titelnummern zwischen 1 und {count} ein.",
        "fr": "❌ Entre des numéros de morceaux valides entre 1 et {count}.",
    },
    "removed": {
        "en": "🗑️ **Removed {count} track(s) from your playlist.** *(Queue: **{total}**)*",
        "tr": "🗑️ **Kuyruktan {count} parça çıkarıldı.** *(Kuyruk: **{total}**)*",
        "de": "🗑️ **{count} Titel entfernt.** *(Warteschlange: **{total}**)*",
        "fr": "🗑️ **{count} morceau(x) retiré(s).** *(File : **{total}**)*",
    },
    "moved": {
        "en": "🔄 **Moved!** `{title}` is now at position **{position}**.",
        "tr": "🔄 **Taşındı!** `{title}` artık **{position}**. sırada.",
        "de": "🔄 **Verschoben!** `{title}` ist jetzt an Position **{position}**.",
        "fr": "🔄 **Déplacé !** `{title}` est maintenant en position **{position}**.",
    },
    "move_too_few": {
        "en": "❌ Not enough videos in playlist to move.",
        "tr": "❌ Taşımak için kuyrukta yeterli video yok.",
        "de": "❌ Nicht genug Videos in der Playlist zum Verschieben.",
        "fr": "❌ Pas assez de vidéos pour déplacer.",
    },
    "invalid_track_numbers": {
        "en": "❌ Invalid track numbers.",
        "tr": "❌ Geçersiz parça numaraları.",
        "de": "❌ Ungültige Titelnummern.",
        "fr": "❌ Numéros de morceaux invalides.",
    },
    "shuffled": {
        "en": "🔀 **Playlist successfully shuffled!** *({count} tracks)*",
        "tr": "🔀 **Kuyruk karıştırıldı!** *({count} parça)*",
        "de": "🔀 **Playlist gemischt!** *({count} Titel)*",
        "fr": "🔀 **Playlist mélangée !** *({count} morceaux)*",
    },
    "shuffle_too_few": {
        "en": "❌ You need at least two tracks in the queue to shuffle.",
        "tr": "❌ Karıştırmak için kuyrukta en az iki parça olmalı.",
        "de": "❌ Zum Mischen brauchst du mindestens zwei Titel.",
        "fr": "❌ Il faut au moins deux morceaux pour mélanger.",
    },
    "cleared": {
        "en": "🗑️ **Playlist cleared.**",
        "tr": "🗑️ **Kuyruk temizlendi.**",
        "de": "🗑️ **Playlist geleert.**",
        "fr": "🗑️ **Playlist vidée.**",
    },
    "starting": {
        "en": "▶️ **Starting:**",
        "tr": "▶️ **Başlatılıyor:**",
        "de": "▶️ **Startet:**",
        "fr": "▶️ **Lancement :**",
    },
    "skipping": {
        "en": "⏭️ **Skipping:**",
        "tr": "⏭️ **Geçiliyor:**",
        "de": "⏭️ **Überspringen:**",
        "fr": "⏭️ **Passage :**",
    },
    "remaining": {
        "en": "*(Remaining: **{count}**)*",
        "tr": "*(Kalan: **{count}**)*",
        "de": "*(Verbleibend: **{count}**)*",
        "fr": "*(Restant : **{count}**)*",
    },
    "no_more_tracks": {
        "en": "❌ No more upcoming tracks in the queue!",
        "tr": "❌ Kuyrukta sıradaki parça kalmadı!",
        "de": "❌ Keine weiteren Titel in der Warteschlange!",
        "fr": "❌ Plus de morceaux à venir dans la file !",
    },
    "invalid_track": {
        "en": "❌ Invalid track number.",
        "tr": "❌ Geçersiz parça numarası.",
        "de": "❌ Ungültige Titelnummer.",
        "fr": "❌ Numéro de morceau invalide.",
    },

    # -- external links / playlists --------------------------------------
    "analyzing_playlist": {
        "en": "🔄 **Analyzing Playlist...**",
        "tr": "🔄 **Oynatma Listesi İnceleniyor...**",
        "de": "🔄 **Playlist wird analysiert...**",
        "fr": "🔄 **Analyse de la playlist...**",
    },
    "playlist_added": {
        "en": "✅ **Playlist Processed:** Added `{count}` videos! *(Queue: **{total}**)*",
        "tr": "✅ **Liste İşlendi:** `{count}` video eklendi! *(Kuyruk: **{total}**)*",
        "de": "✅ **Playlist verarbeitet:** `{count}` Videos hinzugefügt! *(Warteschlange: **{total}**)*",
        "fr": "✅ **Playlist traitée :** `{count}` vidéos ajoutées ! *(File : **{total}**)*",
    },
    "playlist_capped": {
        "en": "ℹ️ Only the first {cap} videos were taken — YouTube does not serve more than that to an anonymous session.",
        "tr": "ℹ️ Yalnızca ilk {cap} video alındı — YouTube anonim oturuma daha fazlasını vermiyor.",
        "de": "ℹ️ Nur die ersten {cap} Videos wurden übernommen — mehr gibt YouTube einer anonymen Sitzung nicht.",
        "fr": "ℹ️ Seules les {cap} premières vidéos ont été prises — YouTube n'en donne pas plus à une session anonyme.",
    },
    "playlist_private": {
        "en": "🔒 **That playlist is private or unlisted.** The bot signs in to nothing, so it cannot read it. Set it to Public and try again.",
        "tr": "🔒 **Bu liste gizli veya özel.** Bot hiçbir hesaba giriş yapmıyor, o yüzden göremiyor. Listeyi Herkese Açık yapıp tekrar dene.",
        "de": "🔒 **Diese Playlist ist privat oder nicht gelistet.** Der Bot meldet sich nirgends an und kann sie nicht lesen. Stelle sie auf Öffentlich.",
        "fr": "🔒 **Cette playlist est privée ou non répertoriée.** Le bot ne se connecte à rien et ne peut pas la lire. Mets-la en Public.",
    },
    "playlist_failed": {
        "en": "❌ Could not extract videos from that playlist.",
        "tr": "❌ Bu listeden video çıkarılamadı.",
        "de": "❌ Aus dieser Playlist konnten keine Videos gelesen werden.",
        "fr": "❌ Impossible d'extraire les vidéos de cette playlist.",
    },
    "invalid_link": {
        "en": "❌ Invalid YouTube link.",
        "tr": "❌ Geçersiz YouTube bağlantısı.",
        "de": "❌ Ungültiger YouTube-Link.",
        "fr": "❌ Lien YouTube invalide.",
    },
    "link_added": {
        "en": "✅ **External Link Added:** `{title}` *(Queue: **{total}**)*",
        "tr": "✅ **Dış Bağlantı Eklendi:** `{title}` *(Kuyruk: **{total}**)*",
        "de": "✅ **Externer Link hinzugefügt:** `{title}` *(Warteschlange: **{total}**)*",
        "fr": "✅ **Lien externe ajouté :** `{title}` *(File : **{total}**)*",
    },

    # -- grid ------------------------------------------------------------
    "grid_live": {"en": "● LIVE", "tr": "● CANLI", "de": "● LIVE", "fr": "● DIRECT"},
    "grid_upcoming": {
        "en": "UPCOMING", "tr": "YAKINDA", "de": "DEMNÄCHST", "fr": "À VENIR",
    },
    "grid_no_preview": {
        "en": "no preview", "tr": "görsel yok", "de": "keine Vorschau", "fr": "pas d'aperçu",
    },
    "grid_results": {
        "en": "{count} results", "tr": "{count} sonuç",
        "de": "{count} Ergebnisse", "fr": "{count} résultats",
    },
    "grid_page": {
        "en": "page {page}/{pages}", "tr": "sayfa {page}/{pages}",
        "de": "Seite {page}/{pages}", "fr": "page {page}/{pages}",
    },
    "grid_shorts_filtered": {
        "en": "Shorts filtered", "tr": "Shorts filtrelendi",
        "de": "Shorts gefiltert", "fr": "Shorts filtrés",
    },
    "live_stream_title": {
        "en": "{channel} Live Stream.",
        "tr": "{channel} Canlı Yayın.",
        "de": "{channel} Livestream.",
        "fr": "{channel} Direct.",
    },

    # -- pagination hint under the grid ----------------------------------
    "grid_caption": {
        "en": "**{header}** — Page **{page}/{pages}**\n*(Click a button, type `{prefix}p <num>` to play, or `{prefix}add <num>` to queue)*",
        "tr": "**{header}** — Sayfa **{page}/{pages}**\n*(Bir düğmeye bas, oynatmak için `{prefix}p <num>`, kuyruğa eklemek için `{prefix}add <num>` yaz)*",
        "de": "**{header}** — Seite **{page}/{pages}**\n*(Auf einen Knopf klicken, `{prefix}p <Nr>` zum Abspielen oder `{prefix}add <Nr>` für die Warteschlange)*",
        "fr": "**{header}** — Page **{page}/{pages}**\n*(Clique un bouton, tape `{prefix}p <num>` pour lire, ou `{prefix}add <num>` pour la file)*",
    },
    "nav_not_owner": {
        "en": "Only the person who ran the search can turn these pages — try `{prefix}s <query>` for your own.",
        "tr": "Bu sayfaları yalnızca aramayı yapan kişi çevirebilir — kendi aramanız için `{prefix}s <sorgu>` deneyin.",
        "de": "Nur wer die Suche gestartet hat, kann umblättern — nutze `{prefix}s <Suche>` für deine eigene.",
        "fr": "Seule la personne qui a lancé la recherche peut tourner les pages — fais `{prefix}s <requête>`.",
    },

    # -- vault -----------------------------------------------------------
    "vault_empty": {
        "en": "📭 **Your Vault is empty!** Use `{prefix}savepl <name>` to save your current queue.",
        "tr": "📭 **Kasan boş!** Kuyruğunu kaydetmek için `{prefix}savepl <ad>` kullan.",
        "de": "📭 **Dein Tresor ist leer!** Nutze `{prefix}savepl <Name>`, um die Warteschlange zu speichern.",
        "fr": "📭 **Ton coffre est vide !** Utilise `{prefix}savepl <nom>` pour sauvegarder ta file.",
    },
    "vault_saved": {
        "en": "💾 **Vault Locked!** Saved as `{name}` — {count} tracks.\nShare code: `{code}`",
        "tr": "💾 **Kasa Kilitlendi!** `{name}` olarak kaydedildi — {count} parça.\nPaylaşım kodu: `{code}`",
        "de": "💾 **Tresor verriegelt!** Als `{name}` gespeichert — {count} Titel.\nTeilen-Code: `{code}`",
        "fr": "💾 **Coffre verrouillé !** Enregistré comme `{name}` — {count} morceaux.\nCode de partage : `{code}`",
    },
    "vault_nothing_to_save": {
        "en": "❌ Your queue is empty! Nothing to save.",
        "tr": "❌ Kuyruğun boş! Kaydedilecek bir şey yok.",
        "de": "❌ Deine Warteschlange ist leer! Nichts zu speichern.",
        "fr": "❌ Ta file est vide ! Rien à sauvegarder.",
    },
    "vault_loaded": {
        "en": "📂 **Vault Opened!** `{name}` inserted into your queue — {count} tracks. *(Queue: **{total}**)*",
        "tr": "📂 **Kasa Açıldı!** `{name}` kuyruğuna eklendi — {count} parça. *(Kuyruk: **{total}**)*",
        "de": "📂 **Tresor geöffnet!** `{name}` in die Warteschlange eingefügt — {count} Titel. *(Warteschlange: **{total}**)*",
        "fr": "📂 **Coffre ouvert !** `{name}` ajouté à ta file — {count} morceaux. *(File : **{total}**)*",
    },
    "vault_not_found": {
        "en": "❌ Could not find a saved playlist by the name or number: `{ref}`!",
        "tr": "❌ Şu ad veya numarayla kayıtlı liste bulunamadı: `{ref}`!",
        "de": "❌ Keine gespeicherte Playlist mit Name oder Nummer: `{ref}`!",
        "fr": "❌ Aucune playlist trouvée avec ce nom ou ce numéro : `{ref}` !",
    },
    "vault_deleted": {
        "en": "🗑️ **Data Erased!** `{name}` permanently removed from your vault.",
        "tr": "🗑️ **Veri Silindi!** `{name}` kasandan kalıcı olarak kaldırıldı.",
        "de": "🗑️ **Daten gelöscht!** `{name}` dauerhaft aus dem Tresor entfernt.",
        "fr": "🗑️ **Données effacées !** `{name}` supprimé définitivement du coffre.",
    },

    # -- history ---------------------------------------------------------
    "history_empty": {
        "en": "📭 Your history is empty — nothing played yet!",
        "tr": "📭 Geçmişin boş — henüz bir şey oynatmadın!",
        "de": "📭 Dein Verlauf ist leer — noch nichts abgespielt!",
        "fr": "📭 Ton historique est vide — rien de lu pour l'instant !",
    },
    "history_title": {
        "en": "🕵️ Your Playback History (last {count})",
        "tr": "🕵️ İzleme Geçmişin (son {count})",
        "de": "🕵️ Dein Wiedergabeverlauf (letzte {count})",
        "fr": "🕵️ Ton historique de lecture ({count} derniers)",
    },
    "history_footer": {
        "en": "{prefix}clearhistory wipes it.",
        "tr": "{prefix}clearhistory ile temizlenir.",
        "de": "{prefix}clearhistory löscht ihn.",
        "fr": "{prefix}clearhistory l'efface.",
    },
    "history_already_empty": {
        "en": "📭 Your history was already empty.",
        "tr": "📭 Geçmişin zaten boştu.",
        "de": "📭 Dein Verlauf war schon leer.",
        "fr": "📭 Ton historique était déjà vide.",
    },
    "history_cleared": {
        "en": "🧹 **History cleared.** `{count}` record(s) erased — this cannot be undone.",
        "tr": "🧹 **Geçmiş temizlendi.** `{count}` kayıt silindi — geri alınamaz.",
        "de": "🧹 **Verlauf gelöscht.** `{count}` Einträge entfernt — nicht rückgängig machbar.",
        "fr": "🧹 **Historique effacé.** `{count}` entrée(s) supprimée(s) — irréversible.",
    },

    # -- settings --------------------------------------------------------
    "region_current": {
        "en": "📍 **Your Active Region:** `{region}`\n\nType `{prefix}setregion <Code>` to change your search region.\n\n**Available Regions:**\n{list}",
        "tr": "📍 **Aktif Bölgen:** `{region}`\n\nArama bölgeni değiştirmek için `{prefix}setregion <Kod>` yaz.\n\n**Mevcut Bölgeler:**\n{list}",
        "de": "📍 **Deine Region:** `{region}`\n\nTippe `{prefix}setregion <Code>`, um die Suchregion zu ändern.\n\n**Verfügbare Regionen:**\n{list}",
        "fr": "📍 **Ta région active :** `{region}`\n\nTape `{prefix}setregion <Code>` pour changer de région.\n\n**Régions disponibles :**\n{list}",
    },
    "region_set": {
        "en": "✅ <@{user}>, your search region is set to **{region}**.",
        "tr": "✅ <@{user}>, arama bölgen **{region}** olarak ayarlandı.",
        "de": "✅ <@{user}>, deine Suchregion ist jetzt **{region}**.",
        "fr": "✅ <@{user}>, ta région de recherche est **{region}**.",
    },
    "region_invalid": {
        "en": "❌ `{code}` is not a country code. Regions are ISO country codes like `US`, `TR`, `DE` — not language codes.",
        "tr": "❌ `{code}` bir ülke kodu değil. Bölgeler `US`, `TR`, `DE` gibi ISO ülke kodlarıdır — dil kodu değil.",
        "de": "❌ `{code}` ist kein Ländercode. Regionen sind ISO-Ländercodes wie `US`, `TR`, `DE` — keine Sprachcodes.",
        "fr": "❌ `{code}` n'est pas un code pays. Les régions sont des codes ISO comme `US`, `TR`, `DE` — pas des codes de langue.",
    },
    "region_did_you_mean": {
        "en": "❌ `{code}` is a language code, not a country. Did you mean `{prefix}setregion {suggestion}`? For the interface language use `{prefix}language`.",
        "tr": "❌ `{code}` bir dil kodu, ülke kodu değil. `{prefix}setregion {suggestion}` mi demek istedin? Arayüz dili için `{prefix}language` kullan.",
        "de": "❌ `{code}` ist ein Sprachcode, kein Land. Meintest du `{prefix}setregion {suggestion}`? Für die Sprache nutze `{prefix}language`.",
        "fr": "❌ `{code}` est un code de langue, pas un pays. Tu voulais dire `{prefix}setregion {suggestion}` ? Pour la langue, utilise `{prefix}language`.",
    },
    "language_current": {
        "en": "🗣️ **Your interface language:** `{language}`\n\nType `{prefix}language <code>` to change it.\n\n**Available:**\n{list}\n\n*This is separate from `{prefix}setregion`, which picks whose search results you get.*",
        "tr": "🗣️ **Arayüz dilin:** `{language}`\n\nDeğiştirmek için `{prefix}language <kod>` yaz.\n\n**Mevcut:**\n{list}\n\n*Bu, hangi bölgenin arama sonuçlarını aldığını belirleyen `{prefix}setregion`'dan ayrıdır.*",
        "de": "🗣️ **Deine Sprache:** `{language}`\n\nTippe `{prefix}language <Code>` zum Ändern.\n\n**Verfügbar:**\n{list}\n\n*Getrennt von `{prefix}setregion`, das die Suchergebnisse bestimmt.*",
        "fr": "🗣️ **Ta langue :** `{language}`\n\nTape `{prefix}language <code>` pour la changer.\n\n**Disponibles :**\n{list}\n\n*Séparé de `{prefix}setregion`, qui choisit les résultats de recherche.*",
    },
    "language_set": {
        "en": "✅ Interface language set to **{language}**.",
        "tr": "✅ Arayüz dili **{language}** olarak ayarlandı.",
        "de": "✅ Sprache auf **{language}** gesetzt.",
        "fr": "✅ Langue de l'interface : **{language}**.",
    },
    "language_invalid": {
        "en": "❌ `{code}` is not a supported language. Options: {list}",
        "tr": "❌ `{code}` desteklenen bir dil değil. Seçenekler: {list}",
        "de": "❌ `{code}` wird nicht unterstützt. Optionen: {list}",
        "fr": "❌ `{code}` n'est pas une langue prise en charge. Options : {list}",
    },
    "theme_set": {
        "en": "✅ UI theme set to **{theme}**!",
        "tr": "✅ Arayüz teması **{theme}** olarak ayarlandı!",
        "de": "✅ UI-Thema auf **{theme}** gesetzt!",
        "fr": "✅ Thème défini sur **{theme}** !",
    },
    "theme_invalid": {
        "en": "❌ Invalid theme. Options: {list}",
        "tr": "❌ Geçersiz tema. Seçenekler: {list}",
        "de": "❌ Ungültiges Thema. Optionen: {list}",
        "fr": "❌ Thème invalide. Options : {list}",
    },
}


def t(key: str, lang: str | None = None, **fields: object) -> str:
    """Translated string for `key`, formatted with `fields`."""
    entry = STRINGS.get(key)
    if entry is None:
        log.warning("no translation entry for %r", key)
        return key

    language = config.normalise_language(lang)
    template = entry.get(language) or entry.get(config.DEFAULT_LANGUAGE) or key
    if not fields:
        return template
    try:
        return template.format(**fields)
    except (KeyError, IndexError) as exc:
        # A formatting mistake must not take a command down with it.
        log.warning("could not format %r for %r: %s", key, language, exc)
        return template


def coverage() -> dict[str, list[str]]:
    """Keys missing per language. Used by selftest to catch gaps early."""
    missing: dict[str, list[str]] = {}
    for language in config.LANGUAGES:
        gaps = [key for key, entry in STRINGS.items() if language not in entry]
        if gaps:
            missing[language] = gaps
    return missing
