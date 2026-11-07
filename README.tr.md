# Ekrovi

**PrtScr'a bas, ekranında ne varsa Claude sohbetine düşsün.**
Windows · Claude masaüstü uygulaması · [English](README.md)

Claude'a bir hatayı göstermek normalde beş adım: ekran görüntüsü al, kaydet, dosyayı bul, ekle, nerede olduğunu anlat. Ekrovi ile tek tuş. Görüntü açık Claude sohbetinin mesaj kutusuna gider, yanında Claude'un işine yarayan bilgiyle: uygulama, pencere başlığı, saat, farenin yeri ve dosya yolu. Sen bir cümle ekleyip Enter'a basarsın.

| Tuş | Ne gönderir |
|---|---|
| **PrtScr** | Farenin olduğu ekranı |
| **Alt+PrtScr** | Etkin pencereyi |
| **Shift+PrtScr** | Sürüklediğin alanı ya da tıkladığın pencereyi (Esc = iptal) |
| **Ctrl+PrtScr** | 5 sn kayıt, anahtar kareler halinde (tekrar PrtScr = erken durdur) |

- **Kayıt:** Claude video izlemez. Ekrovi 5 sn boyunca saniyede 5 kare alır, ekranın gerçekten değiştiği 4 kareyi gönderir. Değişim küçük bir yerdeyse kareler oraya yakınlaşır.
- **Kırmızı halka** fare imlecini gösterir, mesajda da yazar.
- **Yüzen buton** (ekran / alan / kayıt) ve kayıt göstergesi ekran görüntülerinde görünmez. Sağ tık veya tepsi ikonu: ayarlar.
- **Yapıştırır, göndermez.** `auto_send` açarsan Enter'a da basar (mesaj kutusu boşsa).
- **Yanlış pencereye yazmaz.** Her tuştan önce Claude'un önde olduğunu kontrol eder, değilse durur, görüntüyü panoda bırakır, bildirim verir.
- Her şey yerel: görüntüler betiğin yanındaki klasöre kaydedilir.

## Kurulum
Windows 10 (2004+) veya 11, Python 3.10+, Claude masaüstü uygulaması.
```powershell
git clone https://github.com/yilmaz-yildirim/ekrovi.git
cd ekrovi
.\install.ps1            # Windows ile başlasın istersen -Startup ekle
```
İkinci kez açarsan butonu geri getirir. Komutla da tetiklenir: `pythonw ekrovi.pyw screen | window | area | record | show | quit`

## Ayarlar (`config.json`, hepsi isteğe bağlı)
`auto_send`, `record_seconds` (5), `record_fps` (5), `max_images` (4), `mark_cursor`, `language` (`auto` / `tr` / `en`), `prompt_screen`, `prompt_record`, `show_button`, `exclude_from_capture`, `save_dir` (`captures`), `max_edge` (1568). Ayrıntı: [README.md](README.md#settings).

## Bilmen gerekenler
- Sadece Windows'taki Claude masaüstü uygulamasıyla çalışır; tarayıcıdaki claude.ai ve terminaldeki Claude Code ile değil.
- Uygulamanın mesaj kutusunun yapısına dayanır. Bir güncelleme bunu bozarsa görüntü panoya kopyalanır, bildirim gelir.
- PrtScr artık Ekran Alıntısı Aracı'nı açmaz; onun için **Win+Shift+S**.
- Yönetici olarak çalışan bir pencere öndeyse Windows tuşu iletmez; o zaman butonu kullan.
- Hatalar `ekrovi.log` içinde.

Anthropic ile bağlantısı yoktur. Claude, Anthropic'in ticari markasıdır. Lisans: [MIT](LICENSE).
