# Arquitetura do protótipo

Perfil verificado: ESP32 clássico, MINIR4 original 1.2.0, flash de 4 MB.
A tabela existente é preservada; o CSV do projeto serve apenas para compilar.

| Região | Endereço | Tamanho | Uso |
|---|---|---|---|
| nvs | 0x9000 | 0x10000 | Configuração Sonoff; leitura de Wi-Fi |
| reserve | 0x19000 | 0x4000 | NVS própria HomeKit |
| otadata | 0x1d000 | 0x2000 | Seleção do próximo boot |
| phy_init | 0x1f000 | 0x1000 | Calibração existente |
| ota_0 | 0x20000 | 0x1f0000 | Aplicativo experimental |
| ota_1 | 0x210000 | 0x1f0000 | Original Sonoff preservado |

A inicialização seleciona o original para o próximo boot antes de iniciar os
serviços. Falha após essa seleção permite retorno ao original; uma falha
anterior a `app_main` não tem essa garantia. Trial retorna em 20 minutos.
Confirmação explícita depende de pareamento e comandos HomeKit on/off, com NVS
saudável, e vincula a permanência ao hash nativo da imagem. Não é automática.

A aplicação verifica o hash do original antes de selecioná-lo. O backend NVS
só aceita `reserve` no endereço/tamanho esperado e valida a marca de proprietário
antes de inicializar. Não apaga a partição em erro. Namespace de controle não
fica disponível ao SDK; factory/setup é somente leitura. Escritas do driver
Wi-Fi foram desativadas. APIs internas do IDF na leitura da NVS original não
foram provadas inteiramente livres de manutenção interna; não há erase em erro.

Wi-Fi é obtido do blob `pair/info` (176 bytes, magic0x55aa, versão2): SSID em71,
senha em104, validando limites e terminadores. Há fallback para campos do SDK
antigo e AP protegido se não conectar. Nenhuma credencial é publicada.

GPIO26 controla o relé, GPIO19 o LED, GPIO0 o botão e GPIO27 a entrada externa.
MFi/I2C não é habilitado: pinos padrão de exemplos conflitam com este hardware.
HomeKit usa TCP80, manutenção autenticada TCP8080 e descoberta mDNS.

O SDK padrão usa NVS com políticas que poderiam apagar em alguns erros. O
componente local substitui esse backend por armazenamento limitado, falha sem
apagar e impede erase de partição pelo SDK. Não há atualizador OTA HomeKit.

Atualizar exige retornar ao Sonoff e confirmar versão/identidade antes de
usar OTA proprietário para substituir `ota_0`. O novo build começa em teste e
precisa ser validado. Não executar OTA Sonoff com HomeKit em execução, pois o
slot oposto contém o original. Primeira gravação antecede o backup completo.

A confirmação persistida seleciona HomeKit para boots seguintes. Em16/11/2026,
o usuário validou reconexão e estado correto no Casa após corte real de energia. [Resultado dos ensaios](../docs/RESULTADO_0_2_2.md).
