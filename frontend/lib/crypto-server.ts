import crypto from "crypto";

const ENCRYPTION_KEY = process.env.NEXT_PUBLIC_ENCRYPTION_KEY || "";

export function encryptPayload(data: object): string {
  const jsonString = JSON.stringify(data);

  // Generate random salt (8 bytes)
  const salt = crypto.randomBytes(8);

  // Derive key and IV using OpenSSL EVP_BytesToKey (MD5-based)
  const { key, iv } = evpBytesToKey(ENCRYPTION_KEY, salt, 32, 16);

  // Encrypt with AES-256-CBC
  const cipher = crypto.createCipheriv("aes-256-cbc", key, iv);
  let encrypted = cipher.update(jsonString, "utf8");
  encrypted = Buffer.concat([encrypted, cipher.final()]);

  // Format: "Salted__" + salt + ciphertext (OpenSSL compatible)
  const result = Buffer.concat([
    Buffer.from("Salted__"),
    salt,
    encrypted,
  ]);

  return result.toString("base64");
}

function evpBytesToKey(
  password: string,
  salt: Buffer,
  keyLen: number,
  ivLen: number
): { key: Buffer; iv: Buffer } {
  let dtot = Buffer.alloc(0);
  let d = Buffer.alloc(0);
  const passwordBuf = Buffer.from(password);

  while (dtot.length < keyLen + ivLen) {
    d = crypto
      .createHash("md5")
      .update(Buffer.concat([d, passwordBuf, salt]))
      .digest();
    dtot = Buffer.concat([dtot, d]);
  }

  return {
    key: dtot.subarray(0, keyLen),
    iv: dtot.subarray(keyLen, keyLen + ivLen),
  };
}
