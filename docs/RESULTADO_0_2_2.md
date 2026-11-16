# Resultado observado — 0.2.2

Em 15/11/2026, em um MINIR4 ESP32 clássico com original Sonoff 1.2.0:

- HomeKit nativo iniciou na rede existente, sem computador atuando como bridge.
- Usuário pareou no Casa e confirmou ligar e desligar a iluminação.
- Interruptor da parede funcionou e o estado no Casa acompanhou a mudança.
- Retorno explícito por Wi-Fi ao original 1.2.0 confirmado por leitura LAN autenticada.
- Mesmo candidato HomeKit reinstalado pelo OTA proprietário.
- Pareamento persistiu; usuário controlou o mesmo acessório sem parear novamente.
- Novo ligar/desligar foi registrado e confirmação explícita foi aceita.
- Status final: `mode=committed`, um controlador, HomeKit pronto, sem erro de NVS.

O candidato tinha 1042820 bytes. Não é distribuído, pois inclui material de
acesso privado. Os relatórios brutos ficam com o proprietário do módulo.

Os 81 testes locais passaram antes dos ensaios. A revisão 0.2.2 corrigiu um
limite insuficiente de sockets: usa 16 compartilhados, quatro clientes HAP e
dois clientes de manutenção, com guarda de compilação.

Ainda não testados: reboot após confirmação, falta/retorno real de energia,
atualização para uma versão diferente e estabilidade por período prolongado.
O ciclo OTA ensaiado regravou a mesma versão. Não extrapolar esse resultado
para outros modelos, firmwares, layouts ou cargas.
