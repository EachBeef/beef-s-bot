from OpenSSL import crypto
import os

def generate_self_signed_cert():
    # Cria a chave privada
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 2048)

    # Cria o certificado
    cert = crypto.X509()
    cert.get_subject().C = "BR"
    cert.get_subject().ST = "SP"
    cert.get_subject().L = "Sao Paulo"
    cert.get_subject().O = "Bifes Bot"
    cert.get_subject().OU = "IT"
    cert.get_subject().CN = "bifesbot"
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(10*365*24*60*60) # Valido por 10 anos
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, 'sha256')

    # Salva os arquivos
    with open("cert.pem", "wt") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode("utf-8"))
    
    with open("key.pem", "wt") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k).decode("utf-8"))

    print("✅ Certificados 'cert.pem' e 'key.pem' gerados com sucesso!")

if __name__ == "__main__":
    generate_self_signed_cert()