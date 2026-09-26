# Intermedio TLS de la fuente UBB

El servidor `www.ubiobio.cl` entrega únicamente su certificado final. El monitor incorpora el intermedio que falta para construir la cadena completa hasta una raíz del sistema; mantiene verificación de nombre, fecha, firma y raíz. No utiliza `CERT_NONE`, `check_hostname=False` ni `curl -k`.

Emisor: GoGetSSL RSA DV CA, firmado por USERTrust RSA Certification Authority. Expira el 5 de septiembre de 2028.

Fuente oficial: https://www.gogetssl.com/wiki/intermediate-certificates/gogetssl-intermediate-root-certificates/
Descarga: https://gogetssl-cdn.s3.eu-central-1.amazonaws.com/wiki/gogetssl-rsa-dv-ca.txt
SHA-256 DER: `43cac31ef8e8ba1b4b16b8206e4c0a26c5badb2fc3aa09e90170e41b66c2fd64`.

Se verificaron la firma del intermedio y la cadena del servidor con `openssl verify`, usando las raíces ya confiables del sistema. El monitor fija esa huella y desactiva únicamente `VERIFY_X509_PARTIAL_CHAIN`, para exigir una cadena completa. Este complemento sólo se usa para `ubiobio.cl` y `www.ubiobio.cl`.
