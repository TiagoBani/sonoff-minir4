# Aplicativo HomeKit MINIR4

Implementação experimental específica para o layout descrito em
[arquitetura](../homekit-plan/ARQUITETURA.md), usando o SDK Espressif fixado.
As instruções de preparação, compilação, teste e manutenção estão no
[README principal](../README.md). Resultado real em [0.2.2](../docs/RESULTADO_0_2_2.md).

Inclui Lightbulb, GPIOs, NVS própria, Wi-Fi herdado e manutenção autenticada.
Não altera eFuses nem publica imagens binárias. O arquivo privado
`pairing.local.h` contém setup ID/salt/verifier e é gerado localmente.
O token e senha do AP vêm do privado `../minir4-readout/main/access.local.h`.

Firmware foi compilado com IDF5.3.1, DIO40MHz/4MB. A tabela de partições do build
não deve ser gravada. Use somente firmware.bin no envelope OTA validado.
Candidatos novos precisam de hash próprio e novo teste; a confirmação é
vinculada ao hash, sem herdar permanência de outra imagem.

O projeto mantém o SDK como dependência externa, exclui MFi/I2C e extras de OTA,
e substitui seu backend NVS. `dependencies.lock` fixa as dependências gerenciadas.
