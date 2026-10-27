import io

T = {
 "de":  ["Hardware & Magazin","Drucker","Zufuhr","Ablage","bereit","benutzt","leer","belegt",
         "Klick auf den Status-Regler wechselt bereit → benutzt → leer → belegt.","Etikett Fach {{id}}",
         "Befehle bearbeiten","Modus","Simulation","Befehle","Zeitlimit (s)",
         "Befehl: Tür auf","Befehl: Tür zu","Befehl: Tür-Status","Befehl: Plattenwechsel","Befehl: Not-Halt",
         "Protokoll","Keine Aktionen protokolliert.","Befehle laufen lokal auf dem Bambuddy-Rechner; Statusmeldungen dürfen DOOR:OPEN/CLOSED enthalten.",
         "Tür öffnen","Tür schließen","Plattenwechsel","Magazin auffüllen","Magazin editiert","Not-Halt","Konfiguration geändert"],
 "en":  ["Hardware & magazine","Printer","Supply","Storage","ready","used","empty","occupied",
         "Click the status chip to cycle ready → used → empty → occupied.","Label slot {{id}}",
         "Edit commands","Mode","Simulation","Commands","Timeout (s)",
         "Command: door open","Command: door close","Command: door status","Command: plate change","Command: emergency stop",
         "Protocol","No actions logged.","Commands run locally on the Bambuddy host; command output may report DOOR:OPEN/CLOSED.",
         "Open door","Close door","Plate change","Refill magazine","Magazine edited","Emergency stop","Configuration changed"],
 "es":  ["Hardware y cargador","Impresora","Suministro","Almacén","lista","usada","vacía","ocupada",
         "Haga clic en el chip de estado para alternar lista → usada → vacía → ocupada.","Etiqueta casilla {{id}}",
         "Editar comandos","Modo","Simulación","Comandos","Tiempo límite (s)",
         "Comando: abrir puerta","Comando: cerrar puerta","Comando: estado puerta","Comando: cambio de placa","Comando: parada de emergencia",
         "Protocolo","Sin acciones registradas.","Los comandos se ejecutan localmente; la salida puede contener DOOR:OPEN/CLOSED.",
         "Abrir puerta","Cerrar puerta","Cambio de placa","Recargar cargador","Cargador editado","Parada de emergencia","Configuración cambiada"],
 "fr":  ["Matériel et chargeur","Imprimante","Fourniture","Rangement","prête","utilisée","vide","occupée",
         "Cliquez sur la pastille d'état pour passer de prête → utilisée → vide → occupée.","Étiquette case {{id}}",
         "Modifier les commandes","Mode","Simulation","Commandes","Délai (s)",
         "Commande : porte ouverte","Commande : porte fermée","Commande : état porte","Commande : changement de plaque","Commande : arrêt d'urgence",
         "Journal","Aucune action enregistrée.","Les commandes s'exécutent localement ; la sortie peut contenir DOOR:OPEN/CLOSED.",
         "Ouvrir la porte","Fermer la porte","Changement de plaque","Recharger le chargeur","Chargeur modifié","Arrêt d'urgence","Configuration modifiée"],
 "it":  ["Hardware e caricatore","Stampante","Fornitura","Deposito","pronta","usata","vuota","occupata",
         "Fare clic sul chip di stato per passare da pronta → usata → vuota → occupata.","Etichetta cella {{id}}",
         "Modifica comandi","Modalità","Simulazione","Comandi","Timeout (s)",
         "Comando: apri porta","Comando: chiudi porta","Comando: stato porta","Comando: cambio piastra","Comando: arresto di emergenza",
         "Registro","Nessuna azione registrata.","I comandi vengono eseguiti localmente; l'output può contenere DOOR:OPEN/CLOSED.",
         "Apri porta","Chiudi porta","Cambio piastra","Ricarica caricatore","Caricatore modificato","Arresto emergenza","Configurazione modificata"],
 "ja":  ["ハードウェアとマガジン","プリンター","供給","保管","準備完了","使用済み","空き","占有",
         "状態チップをクリックすると 準備完了 → 使用済み → 空き → 占有 と切り替わります。","スロット{{id}}のラベル",
         "コマンドを編集","モード","シミュレーション","コマンド","タイムアウト(秒)",
         "コマンド: ドア開","コマンド: ドア閉","コマンド: ドア状態","コマンド: プラット交換","コマンド: 緊急停止",
         "記録","記録された操作はありません。","コマンドはBambuddyホスト上で実行されます。出力に DOOR:OPEN/CLOSED を含められます。",
         "ドアを開ける","ドアを閉める","プラット交換","マガジン補充","マガジン編集","緊急停止","設定を変更"],
 "ko":  ["하드웨어 및 매거진","프린터","공급","보관","준비됨","사용됨","비어 있음","차지됨",
         "상태 칩을 클릭하면 준비됨 → 사용됨 → 비어 있음 → 차지됨 순으로 바뀝니다.","슬롯 {{id}} 라벨",
         "명령 편집","모드","시뮬레이션","명령","제한 시간(초)",
         "명령: 문 열기","명령: 문 닫기","명령: 문 상태","명령: 플레이트 교체","명령: 비상 정지",
         "기록","기록된 작업이 없습니다.","명령은 Bambuddy 호스트에서 로컬로 실행되며, 출력에 DOOR:OPEN/CLOSED을 포함할 수 있습니다.",
         "문 열기","문 닫기","플레이트 교체","매거진 채우기","매거진 편집","비상 정지","설정 변경됨"],
 "nl":  ["Hardware en magazijn","Printer","Aanvoer","Magazijn","gereed","gebruikt","leeg","bezet",
         "Klik op de statuschip om te wisselen: gereed → gebruikt → leeg → bezet.","Label vak {{id}}",
         "Commando's bewerken","Modus","Simulatie","Commando's","Tijdslimiet (s)",
         "Commando: deur open","Commando: deur dicht","Commando: deurstatus","Commando: plaatwissel","Commando: noodstop",
         "Logboek","Geen acties gelogd.","Commando's draaien lokaal op de Bambuddy-host; de uitvoer mag DOOR:OPEN/CLOSED bevatten.",
         "Deur openen","Deur sluiten","Plaatwissel","Magazijn bijvullen","Magazijn bewerkt","Noodstop","Configuratie gewijzigd"],
 "pt-BR": ["Hardware e carregador","Impressora","Suprimento","Estoque","pronta","usada","vazia","ocupada",
         "Clique no chip de status para alternar pronta → usada → vazia → ocupada.","Etiqueta slot {{id}}",
         "Editar comandos","Modo","Simulação","Comandos","Tempo limite (s)",
         "Comando: abrir porta","Comando: fechar porta","Comando: estado da porta","Comando: troca de placa","Comando: parada de emergência",
         "Registro","Nenhuma ação registrada.","Os comandos rodam localmente; a saída pode conter DOOR:OPEN/CLOSED.",
         "Abrir porta","Fechar porta","Troca de placa","Recarregar carregador","Carregador editado","Parada de emergência","Configuração alterada"],
 "ru":  ["Оборудование и магазин","Принтер","Подача","Хранилище","готова","использована","пуста","занята",
         "Щелчок по плашке состояния: готова → использована → пуста → занята.","Метка ячейки {{id}}",
         "Изменить команды","Режим","Симуляция","Команды","Тайм-аут (с)",
         "Команда: дверь открыть","Команда: дверь закрыть","Команда: состояние двери","Команда: смена пластины","Команда: аварийный стоп",
         "Журнал","Действий не записано.","Команды выполняются локально; вывод может содержать DOOR:OPEN/CLOSED.",
         "Открыть дверь","Закрыть дверь","Смена пластины","Пополнить магазин","Магазин изменён","Аварийный стоп","Конфигурация изменена"],
 "sv":  ["Hårdvara och magasin","Skrivare","Försörjning","Förvaring","redo","använd","tom","upptagen",
         "Klicka på statusrutan för att växla: redo → använd → tom → upptagen.","Etikett fack {{id}}",
         "Redigera kommandon","Läge","Simulering","Kommandon","Tidsgräns (s)",
         "Kommando: öppna dörr","Kommando: stäng dörr","Kommando: dörrläge","Kommando: plåtbyte","Kommando: nödstopp",
         "Logg","Inga åtgärder loggade.","Kommandon körs lokalt på Bambuddy-värden; utdata kan innehålla DOOR:OPEN/CLOSED.",
         "Öppna dörr","Stäng dörr","Plåtbyte","Fyll magasin","Magasin redigerat","Nödstopp","Konfiguration ändrad"],
 "tr":  ["Donanım ve şarjör","Yazıcı","Hizmet","Depo","hazır","kullanıldı","boş","dolu",
         "Durum rozetine tıklayın: hazır → kullanıldı → boş → dolu değişir.","Yuva {{id}} etiketi",
         "Komutları düzenle","Mod","Simülasyon","Komutlar","Zaman aşımı (sn)",
         "Komut: kapıyı aç","Komut: kapıyı kapat","Komut: kapı durumu","Komut: plaka değişimi","Komut: acil durdurma",
         "Kayıt","Kayıtlı işlem yok.","Komutlar yerel çalışır; çıktı DOOR:OPEN/CLOSED içerebilir.",
         "Kapıyı aç","Kapıyı kapat","Plaka değişimi","Şarjörü doldur","Şarjör düzenlendi","Acil durdurma","Yapılandırma değişti"],
 "uk":  ["Обладнання та магазин","Принтер","Подача","Сховище","готова","використана","порожня","зайнята",
         "Клацніть по чипу стану: готова → використана → порожня → зайнята.","Мітка комірки {{id}}",
         "Змінити команди","Режим","Симуляція","Команди","Тайм-аут (с)",
         "Команда: двері відкрити","Команда: двері закрити","Команда: стан дверей","Команда: заміна пластини","Команда: аварійний стоп",
         "Журнал","Дій не записано.","Команди виконуються локально; вивід може містити DOOR:OPEN/CLOSED.",
         "Відкрити двері","Закрити двері","Заміна пластини","Поповнити магазин","Магазин змінено","Аварійний стоп","Конфігурацію змінено"],
 "zh-CN":  ["硬件与料仓","打印机","供料","存储","就绪","已用","空闲","占用",
         "点击状态芯片在 就绪 → 已用 → 空闲 → 占用 之间切换。","槽位 {{id}} 标签",
         "编辑命令","模式","模拟","命令","超时（秒）",
         "命令: 开门","命令: 关门","命令: 门状态","命令: 换板","命令: 急停",
         "日志","尚无操作记录。","命令在 Bambuddy 主机本地执行；输出可包含 DOOR:OPEN/CLOSED。",
         "开门","关门","换板","补料仓","料仓已编辑","急停","配置已更改"],
 "zh-TW":  ["硬體與料匣","印表機","供料","存放","就緒","已用","空閒","佔用",
         "點擊狀態晶片在 就緒 → 已用 → 空閒 → 佔用 之間切換。","槽位 {{id}} 標籤",
         "編輯命令","模式","模擬","命令","逾時（秒）",
         "命令: 開門","命令: 關門","命令: 門狀態","命令: 換板","命令: 緊急停止",
         "日誌","尚無操作記錄。","命令在 Bambuddy 主機本地執行；輸出可包含 DOOR:OPEN/CLOSED。",
         "開門","關門","換板","補料匣","料匣已編輯","緊急停止","設定已更改"],
}
KEYS = ["title","printer","supply","storage","status_ready","status_used","status_empty","status_occupied",
        "statusHint","slotLabel","editConfig","mode","modeSimulated","modeCommand","timeout",
        "cmdDoorOpen","cmdDoorClose","cmdDoorStatus","cmdPlateChange","cmdEmergencyStop",
        "auditTitle","auditEmpty","configHint",
        "action_door_open","action_door_close","action_plate_change","action_magazine_refill",
        "action_magazine_edit","action_emergency_stop","action_hardware_config"]

def esc(s):
    return s.replace("'", "\\'")

for loc, vals in T.items():
    path = f"{loc}.ts"
    src = io.open(path, encoding="utf-8").read()
    if "hardwareAdmin: {" in src:
        print(loc, "already"); continue
    start = src.find("\n  quote: {")
    if start == -1:
        print(loc, "no quote anchor"); continue
    block = "  hardwareAdmin: {\n"
    for k, v in zip(KEYS, vals):
        block += f"    {k}: '{esc(v)}',\n"
    block += "  },\n"
    src = src[:start] + "\n" + block + src[start:]
    io.open(path, "w", encoding="utf-8").write(src)
    print(loc, "ok")