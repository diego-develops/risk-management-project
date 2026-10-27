# Política de debida diligencia y listas de riesgo

> Documento ficticio para laboratorio. Banco Demo, versión 1.0.

## Verificación de identidad
- Umbral mínimo de confianza: 0.8.
- Verificación fallida con confianza igual o superior al umbral: se rechaza la solicitud en línea y se ofrece validación presencial en agencia.
- Confianza inferior al umbral, con o sin verificación exitosa: se escala a revisión manual de identidad.
- Falla técnica de la verificación: se reintenta y se solicita información adicional; no se aprueba sin resultado.

## Consulta de listas de riesgo
- Riesgo bajo: continúa el proceso normal.
- Riesgo medio: debida diligencia reforzada; se solicita información adicional al cliente.
- Riesgo alto: se escala a Cumplimiento y se crea un ticket de escalamiento.
- Falla técnica de la consulta: se reintenta; no se avanza sin resultado.

## Documentos de debida diligencia reforzada
- Declaración de origen de fondos
- Certificado de actividad económica

## Prioridad entre hallazgos
Cuando hay varios hallazgos, prevalece el más restrictivo, en este orden: rechazado, escalado, requiere información, aprobado.
