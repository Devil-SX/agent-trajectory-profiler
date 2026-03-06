use pyo3::prelude::*;

#[pyfunction]
fn classify_characters(text: &str) -> (u64, u64, u64, u64, u64) {
    let mut cjk: u64 = 0;
    let mut latin: u64 = 0;
    let mut digit: u64 = 0;
    let mut whitespace: u64 = 0;
    let mut other: u64 = 0;

    for ch in text.chars() {
        let cp = ch as u32;

        if cp <= 0x7F {
            match cp {
                9 | 10 | 11 | 12 | 13 | 32 => whitespace += 1,
                48..=57 => digit += 1,
                65..=90 | 97..=122 => latin += 1,
                _ => other += 1,
            }
            continue;
        }

        if (0x4E00..=0x9FFF).contains(&cp)
            || (0x3400..=0x4DBF).contains(&cp)
            || (0x3040..=0x30FF).contains(&cp)
            || (0xAC00..=0xD7AF).contains(&cp)
        {
            cjk += 1;
        } else if ch.is_whitespace() {
            whitespace += 1;
        } else if ch.is_numeric() {
            digit += 1;
        } else {
            other += 1;
        }
    }

    (cjk, latin, digit, whitespace, other)
}

#[pymodule]
fn _native(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(classify_characters, m)?)?;
    Ok(())
}
